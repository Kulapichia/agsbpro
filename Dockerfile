# 使用官方Python运行时作为基础镜像
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 安装需要的第三方库
RUN pip install --no-cache-dir requests

# 复制项目文件到容器
COPY . .

# 设置环境变量
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# 运行Python脚本
CMD ["python", "upload-yuancheng.py"]
