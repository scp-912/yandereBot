@echo off
echo 正在启动 YandereBot...

:: 检查虚拟环境是否存在
if not exist "venv" (
    echo 错误：虚拟环境不存在！
    echo 请先运行 install.bat 安装依赖
    pause
    exit
)

:: 激活虚拟环境
call .\venv\Scripts\activate.bat

:: 检查配置文件
if not exist "config.cfg" (
    echo 警告：配置文件不存在，将使用默认配置
)

:: 启动机器人
python bot.py

:: 如果程序异常退出，暂停显示错误信息
if %errorlevel% neq 0 (
    echo.
    echo 程序异常退出！请查看上方错误信息
    pause
)
