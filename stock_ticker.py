import threading
import time
import pystray
from pystray import MenuItem as item
from PIL import Image, ImageDraw
import qstock as qs
import pandas as pd
import os
import sys


def get_app_dir():
    """获取应用程序所在目录（exe 同目录，源码为脚本所在目录）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后：exe 所在目录
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_path(name):
    """获取资源文件路径：优先外部（app 目录），其次打包内嵌资源（sys._MEIPASS）"""
    external = os.path.join(get_app_dir(), name)
    if os.path.exists(external):
        return external
    if getattr(sys, 'frozen', False):
        bundled = os.path.join(sys._MEIPASS, name)
        if os.path.exists(bundled):
            return bundled
    return None


class StockTray:
    def __init__(self):
        self.icon = self.create_icon()
        self.original_icon = self.icon.copy()  # 保存原始图标
        self.stock_data = pd.DataFrame()
        self.current_index = 0
        self.update_interval = 5  # 秒
        self.display_interval = 2  # 秒
        self.running = True
        self.paused = False  # 新增：暂停标志
        self.flashing = False  # 新增：闪烁标志
        self.flash_interval = 0.5  # 闪烁间隔（秒）
        self.price_thresholds = {}  # 新增：价格阈值字典

        # 启动数据更新线程
        threading.Thread(target=self.update_stock_data, daemon=True).start()
        # 启动显示更新线程
        threading.Thread(target=self.update_display, daemon=True).start()
        # 启动闪烁线程
        threading.Thread(target=self.flash_icon, daemon=True).start()

        self.tray = pystray.Icon("stock", self.icon, "行情", menu=self.create_menu())

    def read_price_thresholds(self):
        """读取stocks.txt中的价格阈值"""
        # 清空之前的阈值数据
        self.price_thresholds.clear()
        
        try:
            stocks_file = os.path.join(get_app_dir(), 'stocks.txt')
            if os.path.exists(stocks_file):
                with open(stocks_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            parts = line.split()
                            if len(parts) >= 2:
                                # 格式：代码 价格阈值
                                stock_code = parts[0]
                                try:
                                    threshold = float(parts[1])
                                    self.price_thresholds[stock_code] = threshold
                                    #print(f"设置 {stock_code} 的价格阈值为: {threshold}")
                                except ValueError:
                                    print(f"无法解析价格阈值: {parts[1]}")
        except Exception as e:
            print(f"读取价格阈值出错: {e}")

    def create_icon(self):
        # 优先加载同目录（app 目录）下的水晶包.png作为托盘图标
        icon_path = get_resource_path('水晶包.png')
        if icon_path:
            try:
                image = Image.open(icon_path)
                # pystray推荐64x64，必要时缩放
                if image.size != (64, 64):
                    image = image.resize((64, 64), Image.LANCZOS)
                return image
            except Exception as e:
                print(f"加载水晶包.png失败: {e}")
        # 如果找不到或加载失败，使用默认图标
        image = Image.new('RGB', (64, 64), color=(0, 128, 255))
        d = ImageDraw.Draw(image)
        d.text((10, 25), "股", fill=(255, 255, 255))
        return image

    def create_flash_icon(self):
        """创建闪烁图标（水晶包2.png）"""
        icon_path = get_resource_path('水晶包2.png')
        if icon_path:
            try:
                image = Image.open(icon_path)
                # pystray推荐64x64，必要时缩放
                if image.size != (64, 64):
                    image = image.resize((64, 64), Image.LANCZOS)
                return image
            except Exception as e:
                print(f"加载水晶包2.png失败: {e}")
        # 如果找不到或加载失败，使用红色图标
        image = Image.new('RGB', (64, 64), color=(255, 0, 0))
        d = ImageDraw.Draw(image)
        d.text((10, 25), "警", fill=(255, 255, 255))
        return image

    def read_stock_codes(self):
        try:
            stocks_file = os.path.join(get_app_dir(), 'stocks.txt')
            if not os.path.exists(stocks_file):
                return ['603939']
            with open(stocks_file, 'r', encoding='utf-8') as f:
                stocks = [line.strip().split()[0] for line in f if line.strip()]  # 只取代码部分
            return stocks or ['603939']
        except Exception:
            return ['603939']

    def create_menu(self):
        # 动态生成菜单
        return pystray.Menu(
            item('暂停定时', self.pause_timer, enabled=not self.paused),
            item('恢复定时', self.resume_timer, enabled=self.paused),
            item('退出', self.quit_app)
        )

    def pause_timer(self, icon, item):
        self.paused = True
        self.running = False
        self.tray.menu = self.create_menu()
        self.tray.update_menu()

    def resume_timer(self, icon, item):
        if not self.running:
            self.paused = False
            self.running = True
            # 重新启动线程
            threading.Thread(target=self.update_stock_data, daemon=True).start()
            threading.Thread(target=self.update_display, daemon=True).start()
            threading.Thread(target=self.flash_icon, daemon=True).start()
        self.tray.menu = self.create_menu()
        self.tray.update_menu()

    def check_price_alerts(self):
        """检查价格是否触发警报"""
        if self.stock_data.empty or not self.price_thresholds:
            #print(f"调试: stock_data为空={self.stock_data.empty}, price_thresholds为空={not self.price_thresholds}")
            return False
        
        #print(f"调试: 当前阈值设置: {self.price_thresholds}")
        #print(f"调试: 当前数据列名: {list(self.stock_data.columns)}")
        
        for index, stock in self.stock_data.iterrows():
            # 尝试不同的字段名来获取代码
            stock_code = None
            for code_field in ['代码', 'code', 'symbol', '代码']:
                if code_field in stock:
                    stock_code = str(stock[code_field])
                    break
            
            # 尝试不同的字段名来获取价格
            current_price = None
            for price_field in ['最新', 'price', 'close', 'current_price']:
                if price_field in stock:
                    current_price = stock[price_field]
                    break
            
            #print(f"调试: 行{index} - 代码: {stock_code}, 当前价格: {current_price}")
            
            if stock_code and current_price is not None:
                # 检查是否有对应的阈值
                if stock_code in self.price_thresholds:
                    threshold = self.price_thresholds[stock_code]
                    #print(f"调试: 找到阈值 {threshold} 用于 {stock_code}")
                    try:
                        price = float(current_price)
                       # print(f"调试: 转换后价格 {price}, 阈值 {threshold}, 比较结果 {price <= threshold}")
                        if price <= threshold:
                            #print(f"警报: {stock_code} 当前价格 {price} <= 阈值 {threshold}")
                            return True
                    except (ValueError, TypeError) as e:
                        
                        #print(f"调试: 价格转换失败 {current_price}: {e}")
                        continue
                else:
                    #print(f"调试:  {stock_code} 没有设置阈值")
                    continue
        
        return False

    def create_transparent_icon(self):
        """创建小图标用于闪烁效果"""
        image = Image.new('RGB', (64, 64), color=(255, 255, 255))  # 白色背景
        return image

    def flash_icon(self):
        """图标闪烁线程"""
        print("闪烁线程已启动")
        flash_icon = self.create_flash_icon()
        while self.running:
            if self.flashing:
                print("闪烁状态: 显示水晶包2.png")
                self.tray.icon = flash_icon
                time.sleep(self.flash_interval)
                if self.flashing:  # 再次检查，避免状态改变
                    print("闪烁状态: 显示水晶包.png")
                    self.tray.icon = self.original_icon
                    time.sleep(self.flash_interval)
            else:
                # 非闪烁状态：显示原始图标
                self.tray.icon = self.original_icon
                time.sleep(0.1)  # 短暂休眠

    def update_stock_data(self):
        while self.running:
            try:
                # 每次更新数据时重新读取stocks.txt文件
                self.read_price_thresholds()
                stocks = self.read_stock_codes()
                #print(f"调试: 获取数据: {stocks}")
                data = qs.realtime_data(code=stocks)
                if isinstance(data, pd.DataFrame) and not data.empty:
                    self.stock_data = data
                    #print(f"调试: 获取到数据，共{len(data)}条")
                    # 检查价格警报
                    should_flash = self.check_price_alerts()
                    #print(f"调试: 价格检查结果: should_flash={should_flash}, current_flashing={self.flashing}")
                    if should_flash != self.flashing:
                        self.flashing = should_flash
                        if self.flashing:
                            #print("开始图标闪烁")
                            pass
                        else:
                            #print("停止图标闪烁")
                            pass
                else:
                    print("调试: 未获取到有效的数据")
                time.sleep(self.update_interval)
            except Exception as e:
                print(f"更新数据出错: {e}")
                time.sleep(5)

    def update_display(self):
        while self.running:
            if not self.stock_data.empty:
                try:
                    stock = self.stock_data.iloc[self.current_index]
                    name = stock.get('代码', '未知')
                    price = stock.get('最新', '0.00')
                    t = stock.get('时间', '0.00')
                    change_pct = stock.get('涨幅', '0.00')
                    
                    # 在显示文本中添加闪烁状态指示
                    flash_indicator = " ⚠️" if self.flashing else ""
                    display_text = f"{t} {name} {price} {change_pct}%{flash_indicator}"
                    self.tray.title = display_text
                    self.current_index = (self.current_index + 1) % len(self.stock_data)
                except Exception as e:
                    print(f"更新显示出错: {e}")
            time.sleep(self.display_interval)

    def quit_app(self, icon, item):
        self.running = False
        self.tray.stop()
        sys.exit(0)

    def run(self):
        self.tray.run()

if __name__ == '__main__':
    StockTray().run() 