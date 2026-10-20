"""Small, dependency-free vector controls for the Tkinter desktop shell."""
import math
import tkinter as tk


def draw_icon(canvas, name, x, y, size, color):
    """Draw at a 24-unit grid; no platform emoji/font glyph dependency."""
    s = size / 24
    def line(points, **kw):
        coords = [v for p in points for v in (x+p[0]*s, y+p[1]*s)]
        canvas.create_line(*coords, fill=color, width=max(1.3, 1.6*s),
                           capstyle="round", joinstyle="round", **kw)
    def oval(a, b, c, d, **kw):
        canvas.create_oval(x+a*s, y+b*s, x+c*s, y+d*s, outline=color,
                          width=max(1.3, 1.6*s), **kw)
    if name == "headphones":
        canvas.create_arc(x+4*s, y+3*s, x+20*s, y+20*s, start=0, extent=180,
                          style="arc", outline=color, width=1.8*s)
        for a in (3, 17):
            canvas.create_rectangle(x+a*s, y+11*s, x+(a+4)*s, y+19*s, outline="", fill=color)
        line([(17, 20), (14, 21), (11, 21)])
    elif name == "microphone":
        canvas.create_line(x+12*s, y+5*s, x+12*s, y+12*s, width=7*s,
                           fill=color, capstyle="round")
        canvas.create_arc(x+5*s, y+5*s, x+19*s, y+18*s, start=180, extent=180,
                          style="arc", outline=color, width=1.5*s)
        line([(12, 18), (12, 22)])
        line([(8, 22), (16, 22)])
    elif name == "speaker":
        canvas.create_polygon(*[v for a,b in [(3,9),(7,9),(12,5),(12,19),(7,15),(3,15)]
                                for v in (x+a*s,y+b*s)], fill="", outline=color, width=1.5*s)
        for k in (0, 4):
            canvas.create_arc(x+(11-k)*s, y+(6-k)*s, x+(19+k)*s, y+(18+k)*s,
                              start=-55, extent=110, style="arc", outline=color, width=1.4*s)
    elif name == "file":
        line([(5,2),(14,2),(19,7),(19,22),(5,22),(5,2)])
        line([(14,2),(14,7),(19,7)])
        for v in (12, 16):
            line([(8,v),(16,v)])
    elif name == "settings":
        points=[]
        for i in range(32):
            angle=i*math.pi/16
            radius=10 if i%4 in (1,2) else 8
            points.append((12+radius*math.cos(angle),12+radius*math.sin(angle)))
        canvas.create_polygon(*[v for a,b in points for v in (x+a*s,y+b*s)],
                              fill=color, outline="")
        canvas.create_oval(x+8*s,y+8*s,x+16*s,y+16*s,fill=canvas["bg"],outline="")
    elif name == "play":
        canvas.create_polygon(x+8*s,y+5*s,x+19*s,y+12*s,x+8*s,y+19*s,
                              fill="", outline=color, width=1.7*s)
    elif name == "stop":
        canvas.create_rectangle(x+6*s,y+6*s,x+18*s,y+18*s,fill=color,outline="")
    elif name == "record":
        oval(3,3,21,21)
        oval(7,7,17,17,fill=color)
    elif name == "download":
        line([(12,2),(12,15),(7,10)])
        line([(12,15),(17,10)])
        line([(3,17),(3,21),(21,21),(21,17)])
    elif name == "expand":
        line([(3,9),(3,3),(9,3)])
        line([(15,21),(21,21),(21,15)])
        line([(3,3),(10,10)])
        line([(21,21),(14,14)])
    elif name == "collapse":
        line([(3,3),(10,10),(4,10)])
        line([(10,10),(10,4)])
        line([(21,21),(14,14),(14,20)])
        line([(14,14),(20,14)])
    elif name == "refresh":
        canvas.create_arc(x+4*s,y+4*s,x+20*s,y+20*s,start=35,extent=285,
                          style="arc",outline=color,width=1.5*s)
        line([(21,4),(20,10),(14,9)])


class IconButton(tk.Canvas):
    def __init__(self, parent, app, icon, command, size=30, state="normal"):
        super().__init__(parent, width=size, height=size, bg=app.c["bg"],
                         highlightthickness=0, takefocus=state != "disabled", cursor="hand2")
        self.app, self.icon, self.command = app, icon, command
        self._state, self._hover, self.size = state, False, size
        super().configure(state=state)
        self.bind("<Button-1>", self.invoke)
        self.bind("<space>", self.invoke)
        self.bind("<Return>", self.invoke)
        self.bind("<Enter>", lambda _: self.hover(True))
        self.bind("<Leave>", lambda _: self.hover(False))
        self.bind("<FocusIn>", lambda _: self.draw())
        self.bind("<FocusOut>", lambda _: self.draw())
        self.draw()

    def configure(self, cnf=None, **kw):
        if "state" in kw:
            self._state = kw.pop("state")
            super().configure(takefocus=self._state != "disabled", state=self._state)
        if "icon" in kw:
            self.icon = kw.pop("icon")
        if cnf or kw:
            super().configure(cnf, **kw)
        self.draw()

    config = configure

    def invoke(self, _=None):
        if self._state != "disabled":
            self.command()
        return "break"

    def hover(self, value):
        self._hover = value
        self.draw()

    def draw(self):
        self.delete("all")
        if self._state == "disabled":
            color = self.app.c["track"]
        else:
            color = GREEN if self._hover else self.app.c["text"]
        draw_icon(self, self.icon, (self.size-24)/2, (self.size-24)/2, 24, color)
        if self.tk.call("focus") == str(self):
            self.create_rectangle(1,1,self.size-1,self.size-1,outline=GREEN)


GREEN = "#76b900"


class NavButton(tk.Canvas):
    def __init__(self, parent, app, icon, text, command):
        super().__init__(parent, width=61, height=72, bg=app.c["bg"],
                         highlightthickness=0, takefocus=True, cursor="hand2")
        self.app,self.icon,self.text,self.command=app,icon,text,command
        self.active,self.hovered=False,False
        self.bind("<Button-1>",lambda _:command())
        self.bind("<space>",lambda _:command())
        self.bind("<Return>",lambda _:command())
        self.bind("<Enter>",lambda _:self.hover(True))
        self.bind("<Leave>",lambda _:self.hover(False))
        self.draw()

    def select(self, active):
        self.active=active
        self.draw()

    def hover(self, value):
        self.hovered=value
        self.draw()

    def draw(self):
        bg=self.app.c["header"] if self.active or self.hovered else self.app.c["bg"]
        self.configure(bg=bg)
        self.delete("all")
        color=self.app.c["text"] if self.active else self.app.c["muted"]
        draw_icon(self,self.icon,19,12,24,color)
        self.create_text(31,52,text=self.text,fill=color,font=("Microsoft YaHei UI",-11))
        if self.active:
            self.create_rectangle(0,0,3,72,fill=GREEN,outline="")


class ThinSlider(tk.Canvas):
    """Broadcast-style line and circular thumb with keyboard accessibility."""
    def __init__(self, parent, app, variable, command):
        super().__init__(parent, width=200, height=24, bg=app.c["bg"],
                         highlightthickness=0, takefocus=True, cursor="hand2")
        self.app, self.var, self.command = app, variable, command
        self.bind("<Configure>", lambda _: self.draw())
        self.bind("<Button-1>", self.move)
        self.bind("<B1-Motion>", self.move)
        self.bind("<Left>", lambda _: self.step(-.01))
        self.bind("<Right>", lambda _: self.step(.01))
        self.bind("<Home>", lambda _: self.set(0))
        self.bind("<End>", lambda _: self.set(1))
        self.bind("<FocusIn>", lambda _: self.draw())
        self.bind("<FocusOut>", lambda _: self.draw())
        self.trace = self.var.trace_add("write", lambda *_: self.draw())
        self.bind("<Destroy>", self.dispose)
        self.draw()

    def dispose(self, event):
        if event.widget == self:
            self.var.trace_remove("write", self.trace)

    def set(self, value):
        value = round(min(1, max(0, value)), 2)
        self.var.set(value)
        self.command(value)
        return "break"

    def step(self, step):
        return self.set(self.var.get()+step)

    def move(self, event):
        self.focus_set()
        return self.set((event.x-7)/max(1,self.winfo_width()-14))

    def draw(self):
        self.delete("all")
        w=max(15,self.winfo_width())
        x=7+self.var.get()*(w-14)
        self.create_line(7,12,w-7,12,fill=self.app.c["track"],width=2)
        self.create_line(7,12,x,12,fill=GREEN,width=2)
        self.create_oval(x-5,7,x+5,17,fill=GREEN,outline="")
        if self.tk.call("focus") == str(self):
            self.create_oval(x-8,4,x+8,20,outline=GREEN,width=1)
