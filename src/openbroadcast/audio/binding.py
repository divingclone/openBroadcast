"""Reusable DirectML bindings with separate recurrent input/output buffers."""
import numpy as np
import onnxruntime as ort


class FixedStateBinding:
    """Alternate fixed GPU cache banks, keeping recurrent inputs and outputs apart.

    The caller owns and updates the host input arrays before each run. Host
    output arrays are reused; copy any audio that must survive the next run.
    """

    def __init__(self, session, inputs, state_outputs, outputs, device_id=0):
        # ORT's standalone DML allocator currently ignores nonzero adapter IDs.
        # Never bind such an allocation to a session on another GPU.
        if device_id != 0:
            raise ValueError("Fixed DML state buffers require adapter 0")
        self.session = session
        self.inputs = inputs
        self.outputs = outputs
        self.state_outputs = state_outputs
        types = {"tensor(float)": np.float32, "tensor(float16)": np.float16,
                 "tensor(int32)": np.int32, "tensor(int64)": np.int64}
        descriptors = {item.name: item for item in session.get_inputs()}
        self.zeros = {name: np.zeros(descriptors[name].shape, types[descriptors[name].type])
                      for name in state_outputs}
        self.banks = [
            {name: ort.OrtValue.ortvalue_from_numpy(value, "dml", device_id)
             for name, value in self.zeros.items()}
            for _ in range(2)
        ]
        self.host_outputs = {name: ort.OrtValue.ortvalue_from_numpy(value)
                             for name, value in outputs.items()}
        self.bindings = []
        for index in range(2):
            binding = session.io_binding()
            for name, array in inputs.items():
                binding.bind_cpu_input(name, array)
            for name, value in self.banks[index].items():
                binding.bind_ortvalue_input(name, value)
            for name, output in state_outputs.items():
                binding.bind_ortvalue_output(output, self.banks[1 - index][name])
            for name, value in self.host_outputs.items():
                binding.bind_ortvalue_output(name, value)
            self.bindings.append(binding)
        self.index = 0

    @property
    def states(self):
        return self.banks[self.index]

    def reset(self):
        for name, value in self.banks[0].items():
            value.update_inplace(self.zeros[name])
        self.index = 0

    def run(self):
        binding = self.bindings[self.index]
        # DirectML can upload CPU inputs during binding. Refresh those bindings
        # after the caller updates its array, while retaining all GPU buffers.
        for name, array in self.inputs.items():
            binding.bind_cpu_input(name, array)
        self.session.run_with_iobinding(binding)
        self.index = 1 - self.index
        return self.outputs
