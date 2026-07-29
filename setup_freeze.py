
import sys
from cx_Freeze import setup, Executable

build_exe_options = {
    "packages": ["qstock", "pandas", "PIL", "pystray", "matplotlib","tkinter","seaborn"],
    "include_files": [
        ("水晶包.png", "水晶包.png"),
        ("水晶包2.png", "水晶包2.png"),
        ("stocks.txt", "stocks.txt"),
    ],
    "excludes": [
        "PyQt5", "PyQt6", "PySide2", "PySide6",
        "torch", "tensorflow", "backtrader",
        "sphinx", "docutils", "pytest", "IPython",
        "dask", "distributed", "xarray", "bokeh",
        "sklearn", "cv2", "nltk", "playwright",
        "grpc", "googleapiclient", "langchain",
    ],
    "optimize": 2,
}

base = "Win32GUI"  # 无控制台窗口

setup(
    name="ticker",
    version="2.0",
    description="ticker",
    options={"build_exe": build_exe_options},
    executables=[
        Executable(
            "stock_ticker.py",
            base=base,
            icon="水晶包.ico",
            target_name="ticker.exe",
        )
    ],
)
