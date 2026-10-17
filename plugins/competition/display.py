"""Configurable competition matrix using GSC_calc_1.0.4's original palette."""
import csv
import html
import json
import math
from pathlib import Path
from .rules import result_counts

PALETTE = [
    (204,255,102), (11,123,94), (15,157,120), (125,243,212), (20,210,160),
    (162,0,93), (214,0,123), (255,151,210), (255,87,183),
    (166,92,18), (231,131,29), (255,224,125), (255,192,0),
    (0,86,150), (0,112,192), (129,222,255), (0,176,240),
    (0,146,66), (0,176,80), (178,222,130), (146,208,80),
    (188,0,0), (255,0,0), (255,167,167), (255,91,91),
    (112,48,160), (174,120,214), (89,89,89), (128,128,128), (255,255,255)]
THRESHOLDS = [9,8.5,8,7.5] + [7 - .25 * i for i in range(21)] + [1.5,1,.5,.000001]
HEADER = '#ffff80'
METRICS = ('time', 'bvs', 'stnb')
TIME_RULE = {'Beg':(12,-2), 'Int':(30,-4), 'Exp':(90,-10)}
PADDING = {'Beg':10, 'Int':60, 'Exp':240}


def select_color(start, scale, value):
    index = 29
    for i, threshold in enumerate(THRESHOLDS):
        if (scale > 0 and value >= start + scale * threshold or
                scale < 0 and value < start + scale * threshold):
            index = i
            break
    return '#%02x%02x%02x' % PALETTE[index]


def text_color(background):
    r, g, b = (int(background[i:i+2], 16) for i in (1,3,5))
    return '#ffffff' if 299*r + 587*g + 114*b < 127500 else '#000000'


def load_result(path):
    path = Path(path)
    summary = json.loads(path.read_text(encoding='utf-8'))
    if not all(k in summary for k in ('scores', 'combined')):
        raise ValueError('所选文件不是赛事成绩.json')
    with path.with_name('TopX.csv').open(encoding='utf-8-sig', newline='') as f:
        summary['top_rows'] = list(csv.DictReader(f))
    return summary


def summary_rows(summary):
    """Average / actual Nth ranked result; padded scores are never thresholds."""
    top = {(r['level'], r['metric'], int(r['rank'])): r for r in summary.get('top_rows', [])}
    rows = []
    for level, score in summary['scores'].items():
        n = score['required']
        values = []
        for metric in METRICS:
            decimals = 3 if metric == 'bvs' else 2
            average = score['averages'][metric]
            item = top.get((level, metric, n))
            if item is not None:
                threshold = f'{float(item[metric]):.{decimals}f}'
            else:
                threshold = f'未满Top{n}' if score['available'] < n else '—'
            values.append(f'{average:.{decimals}f} / {threshold}')
        rows.append((level, f"{score['available']}/{n}", *values, f"{score['points']:.2f}"))
    return rows


def build_matrix(summary):
    """Keep the original color matrix style while sizing each level dynamically."""
    counts = result_counts(summary)
    total_count = sum(counts.values())
    starts = {'Beg': (1, 0), 'Int': (1, 4), 'Exp': (counts['Int'] + 4, 4)}
    body_rows = max(counts['Beg'] + 3, counts['Int'] + counts['Exp'] + 6)
    cells = {}
    for row in range(body_rows):
        for col in range(8):
            cells[row,col] = dict(row=row, col=col, span=1, text='', bg=HEADER, fg='#000000', hint='')
    for row in (body_rows,body_rows+1):
        for col, span in ((0,2),(2,2),(4,1),(5,1),(6,1),(7,1)):
            cells[row,col] = dict(row=row, col=col, span=span, text='', bg=HEADER, fg='#000000', hint='')

    def put(row, col, text, color=None, hint=''):
        cell = cells[row,col]
        cell.update(text=str(text), hint=hint)
        if color:
            cell.update(bg=color, fg=text_color(color))

    for col, text in enumerate(('排名','bt','bb','bs','排名','it','ib','is')):
        put(0,col,text)
    for col, text in enumerate(('排名','et','eb','es'),4):
        put(counts['Int']+3,col,text)
    labels = (f'T.{total_count}',f'B.{total_count}',f"BPP{counts['Beg']}",
              f"IPP{counts['Int']}",f"EPP{counts['Exp']}",f'PPP{total_count}')
    for col, text in zip((0,2,4,5,6,7),labels):
        put(body_rows,col,text)
    top = {(r['level'],r['metric'],int(r['rank'])):r for r in summary.get('top_rows', [])}
    scores = summary.get('scores', {})
    for level, n in counts.items():
        first_row, offset = starts[level]
        total_row = first_row+n
        put(total_row,offset,'总计')
        put(total_row+1,offset,'平均')
        for rank in range(1,n+1):
            put(first_row+rank-1,offset,rank)
            for j, metric in enumerate(METRICS):
                item = top.get((level,metric,rank))
                value = float(item[metric]) if item else PADDING[level] if metric=='time' else 0
                hint = (f'{level} {metric} 第{rank}名 | 3BV={item.get("bv", "")} | {item.get("recorded_at", "")} | {item.get("source", "")}'
                        if item else '补位值：当前没有对应的实际录像')
                start, scale = TIME_RULE[level] if metric=='time' else (0,1 if metric=='bvs' else 25)
                decimals = 3 if metric=='bvs' else 2
                put(first_row+rank-1,offset+j+1,f'{value:.{decimals}f}',select_color(start,scale,value),hint)
        for aggregate,row in (('totals',total_row),('averages',total_row+1)):
            for j,metric in enumerate(METRICS):
                value = scores.get(level,{}).get(aggregate,{}).get(metric)
                if value is None:
                    continue
                if metric=='time':
                    start,scale = TIME_RULE[level]
                    if aggregate=='totals':
                        start,scale = start*n,scale*n
                else:
                    start,scale = 0,(1 if metric=='bvs' else 25)*(n if aggregate=='totals' else 1)
                decimals = 3 if metric=='bvs' else 2
                put(row,offset+j+1,f'{value:.{decimals}f}',select_color(start,scale,value))
    combined = summary.get('combined',{})
    time_rule = tuple(sum(TIME_RULE[level][j]*n for level,n in counts.items()) for j in (0,1))
    for col,key,rule,decimals in ((0,f'T{total_count}',time_rule,2),(2,f'B{total_count}',(0,total_count),3)):
        value = combined.get(key)
        if value is not None:
            put(body_rows+1,col,f'{value:.{decimals}f}',select_color(*rule,value))
    for col,level in ((4,'Beg'),(5,'Int'),(6,'Exp'),(7,None)):
        value = combined.get(f'PPP{total_count}') if level is None else scores.get(level,{}).get('points')
        if value is not None:
            put(body_rows+1,col,f'{value:.2f}',select_color(0,1,math.sqrt(max(0,value*2))))
    return list(cells.values())


def render_html(summary):
    cells = build_matrix(summary)
    rows = []
    for row in range(max(c['row'] for c in cells)+1):
        rendered = []
        for c in sorted((c for c in cells if c['row']==row), key=lambda c:c['col']):
            rendered.append(f'<td colspan="{c["span"]}" style="background:{c["bg"]};color:{c["fg"]}" title="{html.escape(c["hint"],quote=True)}">{html.escape(c["text"])}</td>')
        rows.append('<tr>'+''.join(rendered)+'</tr>')
    name = html.escape(str(summary.get('competition_name','赛事')))
    counts = result_counts(summary)
    info = html.escape(f'{summary.get("start", "")} 至 {summary.get("end", "")} | 标识后缀 {summary.get("suffix", "")}')
    enough = '局数足够' if summary.get('combined',{}).get('complete') else '暂定成绩：部分级别局数不足，缺项为补位值'
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{name}成绩记录</title>
<style>body{{margin:24px;background:#f0f0f0;font-family:"Microsoft YaHei",sans-serif;color:#000}}h1{{font-size:23px;margin:0 0 8px}}p{{font-size:13px}}.scroll{{overflow:auto}}table{{table-layout:fixed;border-collapse:collapse;width:676px;font-size:17px;margin:22px 40px}}td{{padding:0;border:1px solid black;text-align:center;height:26px;white-space:nowrap;line-height:26px}}@media print{{body{{background:white;margin:0}}table{{margin:10px 0;width:100%}}}}</style>
<h1>{name} · 成绩记录</h1><p>{info}</p><p>{enough}</p><div class="scroll"><table><colgroup>{'<col>'*8}</colgroup>{''.join(rows)}</table></div>
<p>左侧初级Top{counts['Beg']}；右上中级Top{counts['Int']}；右下高级Top{counts['Exp']}。t=Time，b=3BV/s，s=STNB。配色与GSC_calc_1.0.4一致。</p>
<p>初级参赛录像无3BV门槛；初级计分要求3BV≥10。深色格使用白字，悬停实际成绩可查看录像信息。</p></html>'''
