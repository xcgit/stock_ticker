#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
股票行情系统托盘应用 v2.0
========================
- 系统托盘图标显示实时行情，多股票轮播
- 价格跌破阈值时图标闪烁预警（水晶包2.png）
- 图形化配置窗口管理股票列表和运行参数
- 配置保存至 stocks.txt，可直接用文本编辑器修改

依赖: pip install pystray pillow qstock pandas
"""

import threading
import time
import os
import sys
import tkinter as tk
from tkinter import ttk, messagebox

# ---- 兼容补丁：mock 掉 qstock 不需要但会引发循环导入的重型依赖 ----
import types as _types

# backtrader 在打包环境下有循环导入问题，且本项目不使用回测功能，强制 mock
_bt = _types.ModuleType('backtrader')
_bt.__version__ = '0.0.0'
sys.modules['backtrader'] = _bt
del _bt

# pyfolio 某些环境缺失，按需 mock
try:
    import pyfolio  # noqa: F401
except ImportError:
    _pf = _types.ModuleType('pyfolio')
    _pf.__version__ = '0.0.0'
    sys.modules['pyfolio'] = _pf
    del _pf

del _types

import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw
import qstock as qs
import pandas as pd

# ============================================================
#  stocks.txt 格式说明
# ============================================================
# 文件内容分为两部分：
#
# 第一部分：股票列表（[config] 之前的所有非空、非#行）
#   格式: 股票代码  预警价格阈值(可选)
#   示例:
#     603899
#     512890  1.200
#     603939  20.50
#
# 第二部分：[config] 节（可选）
#   refresh_interval = 5     # 数据刷新间隔（秒）
#   display_interval = 2     # 显示切换间隔（秒）
#   flash_interval   = 0.5   # 闪烁间隔（秒）
# ============================================================

CONFIG_MARKER = '[config]'


def app_dir():
    """获取应用程序所在目录（exe 同目录 / 脚本所在目录）"""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_dir():
    """获取内置资源目录（PyInstaller 解压目录 / 脚本目录）"""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def stocks_file_path():
    """stocks.txt 路径（与 exe 同目录）"""
    return os.path.join(app_dir(), 'stocks.txt')


def icon_file_path(name):
    """图标路径（先找 exe 同目录，再找内置资源）"""
    # 打包后：优先 exe 旁边的用户自定义图标，其次内置默认图标
    external = os.path.join(app_dir(), name)
    if os.path.exists(external):
        return external
    return os.path.join(resource_dir(), name)


# ---------------------------------------------------------------------------
# 文件读写
# ---------------------------------------------------------------------------

def parse_stocks_file(filepath):
    """解析 stocks.txt，返回 (stocks, config_dict)"""
    stocks = []
    config = {}
    in_config = False

    defaults = {
        'refresh_interval': '5',
        'display_interval': '2',
        'flash_interval': '0.5',
    }

    if not os.path.exists(filepath):
        return [('603939', '')], dict(defaults)

    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            raw = line.strip()
            if not raw or raw.startswith('#'):
                continue
            if raw == CONFIG_MARKER:
                in_config = True
                continue
            if in_config:
                if '=' in raw:
                    k, v = raw.split('=', 1)
                    config[k.strip()] = v.strip()
            else:
                parts = raw.split()
                code = parts[0]
                threshold = parts[1] if len(parts) >= 2 else ''
                stocks.append((code, threshold))

    if not stocks:
        stocks.append(('603939', ''))

    for k, v in defaults.items():
        config.setdefault(k, v)

    return stocks, config


def write_stocks_file(filepath, stocks, config):
    """将 stocks 和 config 写回 stocks.txt"""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('# 股票行情配置\n')
        f.write('# 格式: 股票代码  预警价格阈值(可选)\n')
        f.write('# 预警阈值：当股价 <= 阈值时，托盘图标闪烁提示\n')
        f.write('\n')
        for code, threshold in stocks:
            if threshold:
                f.write(f'{code}\t{threshold}\n')
            else:
                f.write(f'{code}\n')
        f.write('\n')
        f.write(f'{CONFIG_MARKER}\n')
        for key, val in config.items():
            f.write(f'{key} = {val}\n')


# ---------------------------------------------------------------------------
# 图片加载
# ---------------------------------------------------------------------------

def load_icon(filename, fallback_color, fallback_text):
    """加载图片，失败时生成纯色 fallback 图标"""
    path = icon_file_path(filename)
    if os.path.exists(path):
        try:
            img = Image.open(path)
            if img.size != (64, 64):
                img = img.resize((64, 64), Image.LANCZOS)
            return img
        except Exception:
            pass
    img = Image.new('RGB', (64, 64), color=fallback_color)
    draw = ImageDraw.Draw(img)
    draw.text((10, 25), fallback_text, fill=(255, 255, 255))
    return img


# ---------------------------------------------------------------------------
# tkinter 配置对话框
# ---------------------------------------------------------------------------

class ConfigDialog:
    """配置窗口 — 管理股票列表 + 运行参数"""

    def __init__(self, parent, stocks, config):
        self.result = None  # (stocks, config) 或 None

        self.window = tk.Toplevel(parent)
        self.window.title('股票行情 配置')
        self.window.geometry('620x540')
        self.window.minsize(520, 460)
        self.window.transient(parent)
        self.window.grab_set()

        main = ttk.Frame(self.window, padding='15')
        main.pack(fill=tk.BOTH, expand=True)

        # ======== 股票列表 ========
        grp_stock = ttk.LabelFrame(main, text='股票代码配置', padding='10')
        grp_stock.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        lst_frame = ttk.Frame(grp_stock)
        lst_frame.pack(fill=tk.BOTH, expand=True)

        scroll = ttk.Scrollbar(lst_frame, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(
            lst_frame,
            selectmode=tk.SINGLE,
            yscrollcommand=scroll.set,
            font=('Consolas', 10),
            height=6,
        )
        scroll.config(command=self.listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        btn_bar = ttk.Frame(grp_stock)
        btn_bar.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_bar, text='添加', width=8, command=self.add_stock).pack(
            side=tk.LEFT, padx=(0, 4)
        )
        ttk.Button(btn_bar, text='编辑', width=8, command=self.edit_stock).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(btn_bar, text='删除', width=8, command=self.delete_stock).pack(
            side=tk.LEFT, padx=4
        )

        # ======== 运行参数 ========
        grp_cfg = ttk.LabelFrame(main, text='运行参数', padding='10')
        grp_cfg.pack(fill=tk.X, pady=(0, 10))

        pad_opts = {'padx': (0, 10), 'pady': 3}
        self._vars = {}

        row = 0
        ttk.Label(grp_cfg, text='数据刷新间隔（秒）:').grid(
            row=row, column=0, sticky=tk.W, **pad_opts
        )
        self._vars['refresh_interval'] = tk.StringVar(
            value=config.get('refresh_interval', '5')
        )
        ttk.Spinbox(
            grp_cfg, from_=1, to=300, textvariable=self._vars['refresh_interval'],
            width=10,
        ).grid(row=row, column=1, sticky=tk.W, pady=3)
        row += 1

        ttk.Label(grp_cfg, text='显示切换间隔（秒）:').grid(
            row=row, column=0, sticky=tk.W, **pad_opts
        )
        self._vars['display_interval'] = tk.StringVar(
            value=config.get('display_interval', '2')
        )
        ttk.Spinbox(
            grp_cfg, from_=1, to=60, textvariable=self._vars['display_interval'],
            width=10,
        ).grid(row=row, column=1, sticky=tk.W, pady=3)
        row += 1

        ttk.Label(grp_cfg, text='闪烁间隔（秒）:').grid(
            row=row, column=0, sticky=tk.W, **pad_opts
        )
        self._vars['flash_interval'] = tk.StringVar(
            value=config.get('flash_interval', '0.5')
        )
        ttk.Spinbox(
            grp_cfg, from_=0.1, to=5, increment=0.1,
            textvariable=self._vars['flash_interval'], width=10,
        ).grid(row=row, column=1, sticky=tk.W, pady=3)
        row += 1

        # ======== 底部按钮 ========
        bottom = ttk.Frame(main)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text='保存', width=10, command=self.save).pack(
            side=tk.RIGHT, padx=(5, 0)
        )
        ttk.Button(bottom, text='取消', width=10, command=self.cancel).pack(
            side=tk.RIGHT
        )

        # 内部数据
        self.stocks = list(stocks)
        self._refresh_listbox()

        # 居中
        self.window.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width() - self.window.winfo_width()) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.window.winfo_height()) // 2
        self.window.geometry(f'+{max(0, px)}+{max(0, py)}')

        self.window.wait_window()

    # ---- 列表操作 ----

    def _refresh_listbox(self):
        self.listbox.delete(0, tk.END)
        for code, th in self.stocks:
            label = f'{code}   阈值: {th}' if th else code
            self.listbox.insert(tk.END, label)

    def _get_selected_index(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning('提示', '请先选择一只股票', parent=self.window)
            return None
        return sel[0]

    def add_stock(self):
        dlg = StockEditDialog(self.window, '添加股票', '', '')
        if dlg.result is not None:
            code, th = dlg.result
            if code:
                self.stocks.append((code, th))
                self._refresh_listbox()

    def edit_stock(self):
        idx = self._get_selected_index()
        if idx is None:
            return
        code, th = self.stocks[idx]
        dlg = StockEditDialog(self.window, '编辑股票', code, th)
        if dlg.result is not None:
            new_code, new_th = dlg.result
            if new_code:
                self.stocks[idx] = (new_code, new_th)
                self._refresh_listbox()

    def delete_stock(self):
        idx = self._get_selected_index()
        if idx is None:
            return
        code = self.stocks[idx][0]
        if messagebox.askyesno('确认删除', f'确定要删除 {code} 吗？', parent=self.window):
            self.stocks.pop(idx)
            self._refresh_listbox()

    # ---- 保存 / 取消 ----

    def save(self):
        try:
            refresh = int(self._vars['refresh_interval'].get())
            display = int(self._vars['display_interval'].get())
            flash = float(self._vars['flash_interval'].get())
            if refresh < 1 or display < 1 or flash <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror(
                '参数错误',
                '请检查参数：\n'
                '  刷新间隔 ≥ 1 秒\n'
                '  显示间隔 ≥ 1 秒\n'
                '  闪烁间隔 > 0 秒',
                parent=self.window,
            )
            return

        cfg = {
            'refresh_interval': str(refresh),
            'display_interval': str(display),
            'flash_interval': str(flash),
        }
        self.result = (self.stocks, cfg)
        self.window.destroy()

    def cancel(self):
        self.window.destroy()


class StockEditDialog:
    """添加/编辑股票的弹窗"""

    def __init__(self, parent, title, code, threshold):
        self.result = None

        self.window = tk.Toplevel(parent)
        self.window.title(title)
        self.window.geometry('320x160')
        self.window.resizable(False, False)
        self.window.transient(parent)
        self.window.grab_set()

        frame = ttk.Frame(self.window, padding='15')
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text='股票代码:').grid(row=0, column=0, sticky=tk.W, pady=5)
        self.entry_code = ttk.Entry(frame, width=22)
        self.entry_code.insert(0, code)
        self.entry_code.grid(row=0, column=1, padx=(10, 0), pady=5)
        self.entry_code.focus_set()

        ttk.Label(frame, text='预警价格阈值:').grid(row=1, column=0, sticky=tk.W, pady=5)
        self.entry_th = ttk.Entry(frame, width=22)
        self.entry_th.insert(0, threshold)
        self.entry_th.grid(row=1, column=1, padx=(10, 0), pady=5)
        ttk.Label(frame, text='（留空则不设预警）').grid(
            row=2, column=1, sticky=tk.W, padx=(10, 0)
        )

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(btn_frame, text='确定', width=8, command=self.ok).pack(
            side=tk.LEFT, padx=5
        )
        ttk.Button(btn_frame, text='取消', width=8, command=self.cancel).pack(
            side=tk.LEFT, padx=5
        )

        # 居中
        self.window.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width() - self.window.winfo_width()) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.window.winfo_height()) // 2
        self.window.geometry(f'+{max(0, px)}+{max(0, py)}')

        # 回车 = 确定
        self.window.bind('<Return>', lambda e: self.ok())

        self.window.wait_window()

    def ok(self):
        code = self.entry_code.get().strip()
        if not code:
            messagebox.showwarning('提示', '请输入股票代码', parent=self.window)
            return
        self.result = (code, self.entry_th.get().strip())
        self.window.destroy()

    def cancel(self):
        self.window.destroy()


# ---------------------------------------------------------------------------
# 系统托盘主程序
# ---------------------------------------------------------------------------

class StockTrayApp:
    """股票行情系统托盘应用"""

    def __init__(self):
        # 读取配置
        self.stocks, self.config = parse_stocks_file(stocks_file_path())
        self._apply_config()

        # 图标
        self.icon_normal = load_icon('水晶包.png', (0, 128, 255), '股')
        self.icon_flash = load_icon('水晶包2.png', (255, 0, 0), '警')
        self.current_icon = self.icon_normal.copy()

        # 状态
        self.stock_data = pd.DataFrame()
        self.current_index = 0
        self.running = True
        self.paused = False
        self.flashing = False
        self.price_thresholds = {}

        # 从 stocks 解析阈值
        self._reload_thresholds()

        # 后台线程
        self._start_threads()

        # 托盘图标
        self.tray = pystray.Icon(
            'stock_ticker',
            self.icon_normal,
            '股票行情',
            menu=self._build_menu(),
        )

        # 隐藏的 tkinter 根窗口
        self.root = tk.Tk()
        self.root.withdraw()

    # ---- 配置 ----

    def _apply_config(self):
        self.update_interval = int(self.config.get('refresh_interval', 5))
        self.display_interval = int(self.config.get('display_interval', 2))
        self.flash_interval = float(self.config.get('flash_interval', 0.5))

    def _reload_thresholds(self):
        self.price_thresholds.clear()
        for code, th in self.stocks:
            if th:
                try:
                    self.price_thresholds[code] = float(th)
                except ValueError:
                    pass

    # ---- 线程管理 ----

    def _start_threads(self):
        threading.Thread(target=self._data_loop, daemon=True).start()
        threading.Thread(target=self._display_loop, daemon=True).start()
        threading.Thread(target=self._flash_loop, daemon=True).start()

    # ---- 托盘菜单 ----

    def _build_menu(self):
        return pystray.Menu(
            item('配置', self.on_config),
            item('暂停', self.on_pause, enabled=not self.paused),
            item('恢复', self.on_resume, enabled=self.paused),
            item('退出', self.on_quit),
        )

    def _update_menu(self):
        self.tray.menu = self._build_menu()
        self.tray.update_menu()

    # ---- 菜单回调 ----

    def on_config(self, icon, menu_item):
        """打开配置窗口（通过 tkinter after 调度到主线程）"""
        self.root.after(0, self._show_config)

    def _show_config(self):
        dlg = ConfigDialog(self.root, self.stocks, self.config)
        if dlg.result is None:
            return  # 用户取消

        new_stocks, new_config = dlg.result

        # 持久化
        write_stocks_file(stocks_file_path(), new_stocks, new_config)

        # 应用到运行中实例
        self.stocks = new_stocks
        self.config = new_config
        self._apply_config()
        self._reload_thresholds()

        # 重置索引，防止越界
        self.current_index = 0
        self.stock_data = pd.DataFrame()

        messagebox.showinfo('提示', '配置已保存，下次数据刷新后生效', parent=self.root)

    def on_pause(self, icon, menu_item):
        self.paused = True
        self.running = False
        self.tray.title = '⏸ 已暂停'
        self._update_menu()

    def on_resume(self, icon, menu_item):
        if not self.running:
            self.paused = False
            self.running = True
            self._start_threads()
        self._update_menu()

    def on_quit(self, icon, menu_item):
        self.running = False
        self.tray.stop()
        self.root.quit()
        os._exit(0)

    # ---- 价格预警 ----

    def _check_alerts(self):
        if self.stock_data.empty or not self.price_thresholds:
            return False
        for _, row in self.stock_data.iterrows():
            code = None
            for k in ('代码', 'code', 'symbol'):
                if k in row:
                    code = str(row[k])
                    break
            price = None
            for k in ('最新', 'price', 'close', 'current_price'):
                if k in row:
                    price = row[k]
                    break
            if code and price is not None and code in self.price_thresholds:
                try:
                    if float(price) <= self.price_thresholds[code]:
                        return True
                except (ValueError, TypeError):
                    pass
        return False

    # ---- 后台循环 ----

    def _data_loop(self):
        """定时拉取行情数据"""
        while self.running:
            try:
                codes = [s[0] for s in self.stocks]
                data = qs.realtime_data(code=codes)
                if isinstance(data, pd.DataFrame) and not data.empty:
                    self.stock_data = data
                    # 检查预警
                    new_flash = self._check_alerts()
                    if new_flash != self.flashing:
                        self.flashing = new_flash
                time.sleep(self.update_interval)
            except Exception as exc:
                print(f'[数据] 出错: {exc}')
                time.sleep(5)

    def _display_loop(self):
        """轮播显示股票行情"""
        while self.running:
            if not self.stock_data.empty:
                try:
                    row = self.stock_data.iloc[self.current_index]
                    name = row.get('代码', '?')
                    price = row.get('最新', '?.??')
                    tm = row.get('时间', '')
                    chg = row.get('涨幅', '0.00')
                    warn = ' ⚠' if self.flashing else ''
                    self.tray.title = f'{tm} {name} {price} {chg}%{warn}'
                    self.current_index = (self.current_index + 1) % len(
                        self.stock_data
                    )
                except Exception as exc:
                    print(f'[显示] 出错: {exc}')
            time.sleep(self.display_interval)

    def _flash_loop(self):
        """图标闪烁线程"""
        while self.running:
            if self.flashing:
                self.tray.icon = self.icon_flash
                time.sleep(self.flash_interval)
                if self.flashing:
                    self.tray.icon = self.icon_normal
                    time.sleep(self.flash_interval)
            else:
                if self.tray.icon is not self.icon_normal:
                    self.tray.icon = self.icon_normal
                time.sleep(0.1)

    # ---- 启动 ----

    def run(self):
        """启动应用（pystray 在后台线程，tkinter 在主线程）"""
        threading.Thread(target=self.tray.run, daemon=True).start()
        self.root.mainloop()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    StockTrayApp().run()
