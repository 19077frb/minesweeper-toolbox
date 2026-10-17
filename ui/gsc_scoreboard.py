import tkinter as tk
from tkinter import ttk
from services.gsc_display import build_matrix


class ScoreboardView(ttk.Frame):
    def __init__(self, master, scale_variable):
        super().__init__(master)
        self.scale_variable = scale_variable
        self.summary = None
        self.cells = []
        self.caption = tk.StringVar(value='运行金羊杯筛选及计算，或打开已有的成绩.json')
        self.info = tk.StringVar(value='左侧初级Top20，右上中级Top12，右下高级Top5；t=Time，b=3BV/s，s=STNB')
        ttk.Label(self, textvariable=self.caption, wraplength=1000).pack(anchor='w', pady=(0,8))
        frame = ttk.Frame(self)
        frame.pack(fill='both',expand=True)
        frame.rowconfigure(0,weight=1)
        frame.columnconfigure(0,weight=1)
        self.canvas = tk.Canvas(frame, background='#f0f0f0', highlightthickness=0, height=520)
        self.canvas.grid(row=0,column=0,sticky='nsew')
        v = ttk.Scrollbar(frame,orient='vertical',command=self.canvas.yview)
        v.grid(row=0,column=1,sticky='ns')
        h = ttk.Scrollbar(frame,orient='horizontal',command=self.canvas.xview)
        h.grid(row=1,column=0,sticky='ew')
        self.canvas.configure(yscrollcommand=v.set,xscrollcommand=h.set)
        self.canvas.bind('<Configure>',lambda e:self.draw())
        self.canvas.bind('<MouseWheel>',self.scroll)
        self.canvas.bind('<Motion>',self.hover)
        self.canvas.bind('<Leave>',lambda e:self.info.set('t=Time，b=3BV/s，s=STNB；颜色阈值沿用原工具'))
        ttk.Label(self,textvariable=self.info,wraplength=1000).pack(anchor='w',pady=(7,0))
        scale_variable.trace_add('write',lambda *a:self.draw())

    def set_data(self, summary):
        self.summary = summary
        self.cells = build_matrix(summary)
        enough = '局数足够' if summary.get('combined',{}).get('complete') else '暂定：局数不足，缺项为补位值'
        self.caption.set(f"金羊杯{summary.get('edition','')} | {summary.get('start','')} 至 {summary.get('end','')} | 后缀 {summary.get('suffix','')} | {enough}")
        self.canvas.yview_moveto(0)
        self.draw()

    def draw(self):
        if not self.winfo_exists():
            return
        self.canvas.delete('all')
        if not self.cells:
            self.canvas.create_text(25,30,anchor='nw',text='暂无成绩记录，请先计算或打开已有成绩文件。',font=('Microsoft YaHei UI',12))
            return
        try:
            size = 20 * int(self.scale_variable.get()) / 100
        except (ValueError,tk.TclError):
            size = 20
        self.row_size = size
        self.column_size = size*3.25
        width, height = 30*size,29*size
        self.origin_x = max(2*size,(self.canvas.winfo_width()-26*size)/2)
        self.origin_y = 2*size
        self.canvas.configure(scrollregion=(0,0,max(width,self.canvas.winfo_width()),height))
        for c in self.cells:
            x = self.origin_x+c['col']*self.column_size
            y = self.origin_y+c['row']*size
            w = c['span']*self.column_size
            self.canvas.create_rectangle(x,y,x+w,y+size,fill=c['bg'],outline='#000000',width=1)
            self.canvas.create_text(x+w/2,y+size/2,text=c['text'],fill=c['fg'],
                                    font=('Microsoft YaHei',-max(8,round(size*2/3))))

    def scroll(self,event):
        self.canvas.yview_scroll(-int(event.delta/120),'units')
        return 'break'

    def hover(self,event):
        if not self.cells:
            return
        row = int((self.canvas.canvasy(event.y)-self.origin_y)//self.row_size)
        col = int((self.canvas.canvasx(event.x)-self.origin_x)//self.column_size)
        cell = next((c for c in self.cells if c['row']==row and c['col']<=col<c['col']+c['span']),None)
        if cell:
            self.info.set(cell['hint'] or cell['text'])
