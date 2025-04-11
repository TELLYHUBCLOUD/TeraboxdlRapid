FROM hrishi2861/terabox:latest

WORKDIR /app

# 🔧 Add this line BEFORE pip install
RUN pip install --upgrade pip setuptools

COPY requirements.txt .

RUN pip3 install --no-cache-dir --break-system-packages -r requirements.txt

COPY . .

CMD ["python", "start.sh"]

