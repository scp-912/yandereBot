@echo off
echo 正在创建虚拟环境...
python -m venv venv
echo 虚拟环境创建完成

echo 激活虚拟环境...
call .\venv\Scripts\activate.bat

echo 开始安装依赖...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo 检查配置文件...
if not exist "config.cfg" (
    echo 配置文件不存在，程序首次运行时会自动创建
)

echo 安装完成！
echo 请编辑 config.cfg 文件配置你的机器人
echo 完成配置后运行 start.bat 启动机器人
pause
