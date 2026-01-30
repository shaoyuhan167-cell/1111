from flask import Flask, request, jsonify, send_file, send_from_directory, render_template_string
import os
import tempfile
import img2pdf
import glob
import requests
import urllib.request
import threading
import queue
import uuid
import time
import shutil
import re
from datetime import datetime
from html.parser import HTMLParser

app = Flask(__name__)

# HTML标签清除器
class MLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []
    
    def handle_data(self, data):
        self.text.append(data)
    
    def get_data(self):
        return ''.join(self.text)

def strip_html_tags(html_text):
    """移除HTML标签，保留文本内容"""
    if not html_text:
        return html_text
    try:
        s = MLStripper()
        s.feed(html_text)
        return s.get_data().strip()
    except:
        # 如果解析失败，使用正则表达式简单处理
        return re.sub(r'<[^>]+>', '', html_text).strip()
# 格式化日期类型 1997-7-1  19970701  1997/07/01  199707  1997-07
def format_release_date(date_str):
    """格式化发布日期"""
    if not date_str:
        return '-'
    
    try:
        date_str = str(date_str).strip()

        # 识别纯数字的时间戳并转换：根据数值大小判断是秒还是毫秒
        if re.fullmatch(r"\d{10,13}", date_str):
            ts = int(date_str)
            # 如果数字很大（>1e11），通常表示毫秒（例如 1990s-2000s 的毫秒数为 1e11 量级）
            if ts > 1e11:
                dt = datetime.fromtimestamp(ts / 1000)
            else:
                dt = datetime.fromtimestamp(ts)
            return dt.strftime('%Y-%m-%d')

        # 尝试多种常见日期格式
        date_formats = [
            '%Y-%m-%d',
            '%Y/%m/%d',
            '%Y%m%d',
            '%Y.%m.%d',
            '%Y-%m',
            '%Y/%m',
            '%Y.%m'
        ]

        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(date_str, fmt)
                return parsed_date.strftime('%Y-%m-%d')
            except ValueError:
                continue

        # 如果都不匹配，返回原字符串
        return date_str
    except:
        return date_str

# 导航HTML页面
HTML_MAIN = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>标准查询系统</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #00FFFF 0%, #C00FFFF 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        
        .container {
            max-width: 600px;
            width: 100%;
            text-align: center;
        }
        
        .logo {
            font-size: 64px;
            margin-bottom: 20px;
            animation: float 3s ease-in-out infinite;
        }
        
        @keyframes float {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-10px); }
        }
        
        h1 {
            color: white;
            font-size: 36px;
            margin-bottom: 10px;
        }
        
        .subtitle {
            color: black;
            font-size: 16px;
            margin-bottom: 40px;
            font-family:Arial;
        }
        
        .nav-buttons {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        
        .nav-card {
            background: white;
            border-radius: 15px;
            padding: 30px 20px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            text-decoration: none;
            color: #333;
            transition: all 0.3s ease;
        }
        
        .nav-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 15px 50px rgba(0,0,0,0.3);
        }
        
        .nav-icon {
            font-size: 48px;
            margin-bottom: 15px;
        }
        
        .nav-card h2 {
            font-size: 22px;
            margin-bottom: 10px;
            color: #333;
        }
        
        .nav-card p {
            font-size: 13px;
            color: #999;
        }
        .h2{
            color:black;
            text-align:center;
            font-size: 40px;
            margin-bottom: 80px;
            font-family:Serif;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">📚</div>
        <h1 class ="h2">标准查询系统</h1>
        <p class="subtitle">快速搜索和下载国家标准文档</p>
        
        <div class="nav-buttons">
            <a href="/search" class="nav-card">
                <div class="nav-icon">🔍</div>
                <h2>搜索标准</h2>
                <p>查询和浏览标准信息</p>
            </a>
            <a href="/download-page" class="nav-card">
                <div class="nav-icon">📥</div>
                <h2>下载标准</h2>
                <p>直接下载标准文档</p>
            </a>
        </div>
    </div>
</body>
</html>
'''

# 下载页面HTML
HTML_SIMPLE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>标准下载器</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #FFFFFF 0%, #00FFFF 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        
        .container {
            max-width: 500px;
            width: 100%;
            background: white;
            border-radius: 15px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
            padding: 40px;
        }
        
        .nav-back {
            display: inline-block;
            color: #667eea;
            text-decoration: none;
            font-size: 14px;
            margin-bottom: 20px;
            transition: all 0.3s ease;
        }
        
        .nav-back:hover {
            color: #764ba2;
        }
        
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        
        .icon {
            font-size: 48px;
            margin-bottom: 15px;
        }
        
        h1 {
            color: #333;
            font-size: 28px;
            margin-bottom: 8px;
        }
        
        .subtitle {
            color: #999;
            font-size: 14px;
        }
        
        .input-group {
            margin-bottom: 20px;
        }
        
        input {
            width: 100%;
            padding: 14px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 14px;
            transition: all 0.3s ease;
            background-color: #f8f9fa;
        }
        
        input:focus {
            outline: none;
            border-color: #667eea;
            background-color: white;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        input::placeholder {
            color: #bbb;
        }
        
        button {
            width: 100%;
            padding: 14px 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
        }
        
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6);
        }
        
        button:active {
            transform: translateY(0);
        }
        
        button:disabled {
            opacity: 0.7;
            cursor: not-allowed;
            transform: none;
        }
        
        .progress {
            margin-top: 30px;
            display: none;
            animation: slideIn 0.3s ease;
        }
        
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .progress-label {
            font-size: 12px;
            color: #666;
            margin-bottom: 8px;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .progress-bar {
            width: 100%;
            background: #e0e0e0;
            height: 6px;
            border-radius: 3px;
            overflow: hidden;
        }
        
        .progress-fill {
            width: 0%;
            background: linear-gradient(90deg, #ffffff 0%, #02d6f1 100%);
            height: 100%;
            transition: width 0.4s ease;
            border-radius: 3px;
        }
        
        .status {
            margin-top: 12px;
            font-size: 13px;
            color: #666;
            text-align: center;
            min-height: 18px;
        }
        
        .error {
            margin-top: 20px;
            padding: 12px 14px;
            background-color: #fee;
            border-left: 4px solid #f44;
            border-radius: 4px;
            color: #c33;
            font-size: 14px;
            display: none;
            animation: slideIn 0.3s ease;
        }
        
        .error.show {
            display: block;
        }
        
        .download-link {
            margin-top: 20px;
            display: none;
            animation: slideIn 0.3s ease;
        }
        
        .download-link.show {
            display: block;
        }
        
        .success-box {
            background: linear-gradient(135deg, #84fab0 0%, #8fd3f4 100%);
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }
        
        .success-icon {
            font-size: 32px;
            margin-bottom: 10px;
        }
        
        .success-text {
            color: #333;
            font-weight: 600;
            margin-bottom: 15px;
        }
        
        .download-button {
            background: white;
            color: #667eea;
            text-decoration: none;
            padding: 10px 24px;
            border-radius: 6px;
            font-weight: 600;
            display: inline-block;
            transition: all 0.3s ease;
        }
        
        .download-button:hover {
            background: #f8f9fa;
        }
        
        .tips {
            margin-top: 25px;
            padding-top: 20px;
            border-top: 1px solid #e0e0e0;
            font-size: 12px;
            color: #999;
            text-align: center;
            line-height: 1.6;
        }
        
        .spinner {
            display: inline-block;
            width: 12px;
            height: 12px;
            border: 2px solid #667eea;
            border-top: 2px solid transparent;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
            margin-right: 6px;
            vertical-align: middle;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
    </style>
</head>
<body>
    <div class="container">
        <a href="/" class="nav-back">← 返回首页</a>
        
        <div class="header">
            <div class="icon">📥</div>
            <h1>标准下载器</h1>
            <p class="subtitle">快速下载国家标准文档</p>
        </div>
        
        <div class="input-group">
            <input type="text" id="standardInput" placeholder="输入标准号，如: GB/T 19001-2016">
        </div>
        
        <button onclick="startDownload()" id="downloadBtn">开始下载</button>
        
        <div class="progress" id="progress">
            <div class="progress-label">下载进度</div>
            <div class="progress-bar"><div class="progress-fill" id="progressFill"></div></div>
            <div class="status" id="status">准备中...</div>
        </div>
        
        <div class="error" id="error"></div>
        
        <div class="download-link" id="downloadLink">
            <div class="success-box">
                <div class="success-icon">✓</div>
                <div class="success-text">下载完成！</div>
                <a href="#" id="downloadAnchor" class="download-button">点击下载 PDF</a>
            </div>
        </div>
        
        <div class="tips">
            💡 提示：输入标准号后按 Enter 或点击按钮即可开始下载
        </div>
    </div>
    
    <script>
        let taskId = null;
        let interval = null;
        
        function startDownload() {
            const standardNum = document.getElementById('standardInput').value.trim();
            const downloadBtn = document.getElementById('downloadBtn');
            
            if (!standardNum) {
                showError('请输入标准号');
                return;
            }
            
            // 清除错误信息
            hideError();
            document.getElementById('progress').style.display = 'block';
            document.getElementById('downloadLink').classList.remove('show');
            downloadBtn.disabled = true;
            downloadBtn.innerHTML = '<span class="spinner"></span>处理中...';
            
            fetch('/api/download', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({standard_num: standardNum})
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    taskId = data.task_id;
                    checkStatus();
                } else {
                    downloadBtn.disabled = false;
                    downloadBtn.innerHTML = '开始下载';
                    showError(data.message || '下载失败');
                }
            })
            .catch(e => {
                downloadBtn.disabled = false;
                downloadBtn.innerHTML = '开始下载';
                showError('网络错误，请检查连接');
            });
        }
        
        function checkStatus() {
            if (interval) clearInterval(interval);
            interval = setInterval(() => {
                fetch('/api/status/' + taskId)
                .then(r => r.json())
                .then(status => {
                    const downloadBtn = document.getElementById('downloadBtn');
                    
                    if (status.status === 'completed') {
                        clearInterval(interval);
                        document.getElementById('status').innerHTML = '<span style="color: #4CAF50;">✓ 完成</span>';
                        document.getElementById('progressFill').style.width = '100%';
                        document.getElementById('downloadAnchor').href = status.download_url;
                        document.getElementById('downloadLink').classList.add('show');
                        
                        downloadBtn.disabled = false;
                        downloadBtn.innerHTML = '重新下载';
                        downloadBtn.style.marginTop = '20px';
                        
                        // 自动打开下载
                        setTimeout(() => {
                            window.open(status.download_url, '_blank');
                        }, 500);
                    } else if (status.status === 'downloading' || status.status === 'converting') {
                        const progress = status.progress || 0;
                        document.getElementById('progressFill').style.width = progress + '%';
                        document.getElementById('status').innerHTML = '<span class="spinner"></span>' + (status.message || '处理中...');
                    } else if (status.status === 'error') {
                        clearInterval(interval);
                        downloadBtn.disabled = false;
                        downloadBtn.innerHTML = '开始下载';
                        showError(status.message || '下载出错');
                    }
                });
            }, 1000);
        }
        
        function showError(msg) {
            const errorEl = document.getElementById('error');
            errorEl.innerHTML = msg;
            errorEl.classList.add('show');
            document.getElementById('progress').style.display = 'none';
        }
        
        function hideError() {
            document.getElementById('error').classList.remove('show');
        }
        
        // 按回车键开始下载
        document.getElementById('standardInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') startDownload();
        });
        
        // 输入框获得焦点时清除错误
        document.getElementById('standardInput').addEventListener('focus', hideError);
    </script>
</body>
</html>
'''

# 搜索页面HTML
HTML_SEARCH = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>搜索标准</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #FFFFFF 0%, #0000FF 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 15px;
            padding: 30px;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
        }
        
        .nav-back {
            display: inline-block;
            color: #667eea;
            text-decoration: none;
            font-size: 14px;
            margin-bottom: 20px;
            transition: all 0.3s ease;
        }
        
        .nav-back:hover {
            color: #764ba2;
        }
        
        .header {
            text-align: center;
            margin-bottom: 30px;
        }
        
        .icon {
            font-size: 48px;
            margin-bottom: 15px;
        }
        
        h1 {
            color: #333;
            font-size: 28px;
            margin-bottom: 8px;
        }
        
        .subtitle {
            color: #999;
            font-size: 14px;
        }
        
        .search-box {
            display: flex;
            gap: 10px;
            margin-bottom: 30px;
        }
        
        .search-input {
            flex: 1;
            padding: 14px 16px;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
            font-size: 14px;
            transition: all 0.3s ease;
        }
        
        .search-input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        .search-button {
            padding: 14px 30px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 8px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s ease;
            white-space: nowrap;
        }
        
        .search-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6);
        }
        
        .search-button:disabled {
            opacity: 0.7;
            cursor: not-allowed;
        }
        
        .info-message {
            padding: 15px;
            background: #f0f8ff;
            border-left: 4px solid #667eea;
            border-radius: 4px;
            margin-bottom: 20px;
            color: #333;
            font-size: 14px;
            display: none;
            animation: slideIn 0.3s ease;
        }
        
        .info-message.show {
            display: block;
        }
        
        .error-message {
            padding: 15px;
            background: #fee;
            border-left: 4px solid #f44;
            border-radius: 4px;
            margin-bottom: 20px;
            color: #c33;
            font-size: 14px;
            display: none;
            animation: slideIn 0.3s ease;
        }
        
        .error-message.show {
            display: block;
        }
        
        @keyframes slideIn {
            from {
                opacity: 0;
                transform: translateY(10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .loading {
            text-align: center;
            padding: 30px;
            display: none;
        }
        
        .loading.show {
            display: block;
        }
        
        .spinner {
            display: inline-block;
            width: 40px;
            height: 40px;
            border: 4px solid #e0e0e0;
            border-top: 4px solid #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .spinner-text {
            margin-top: 10px;
            color: #666;
        }
        
        /* 筛选器样式 */
        .filter-container {
            background: #f8f9fa;
            padding: 15px 20px;
            margin: 20px 0;
            border-radius: 8px;
            display: flex;
            gap: 20px;
            align-items: center;
            flex-wrap: wrap;
        }
        
        .filter-item {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .filter-item label {
            font-weight: 600;
            color: #333;
            white-space: nowrap;
        }
        
        .filter-item select,
        .filter-item input {
            padding: 8px 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            background: white;
            font-size: 14px;
            cursor: pointer;
            min-width: 120px;
        }
        
        .filter-item select:hover,
        .filter-item input:hover {
            border-color: #667eea;
        }
        
        .filter-item input {
            width: 100px;
        }
        
        .filter-button {
            padding: 8px 16px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 600;
            transition: all 0.3s ease;
        }
        
        .filter-button:hover {
            background: #764ba2;
        }
        
        /* 分页样式 */
        .pagination-container {
            margin-top: 30px;
            padding: 20px;
            background: #f8f9fa;
            border-radius: 8px;
            text-align: center;
        }
        
        .pagination-info {
            margin-bottom: 15px;
            font-size: 14px;
            color: #666;
        }
        
        .pagination-buttons {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }
        
        .pagination-btn {
            padding: 8px 16px;
            background: #667eea;
            color: white;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            font-weight: 600;
            transition: all 0.3s ease;
        }
        
        .pagination-btn:hover:not(:disabled) {
            background: #764ba2;
            transform: translateY(-2px);
        }
        
        .pagination-btn:disabled {
            background: #ccc;
            cursor: not-allowed;
        }
        
        .page-numbers {
            display: flex;
            gap: 5px;
            flex-wrap: wrap;
            justify-content: center;
        }
        
        .page-num {
            padding: 6px 12px;
            border: 1px solid #ddd;
            border-radius: 4px;
            cursor: pointer;
            background: white;
            transition: all 0.3s ease;
        }
        
        .page-num:hover {
            border-color: #667eea;
            color: #667eea;
        }
        
        .page-num.active {
            background: #667eea;
            color: white;
            border-color: #667eea;
        }
        
        .table-wrapper {
            overflow-x: auto;
            border-radius: 8px;
            border: 1px solid #e0e0e0;
            display: none;
        }
        
        .table-wrapper.show {
            display: block;
            animation: slideIn 0.3s ease;
        }
        
        table {
            width: 100%;
            border-collapse: collapse;
        }
        
        thead {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        
        th {
            color: white;
            padding: 15px;
            text-align: left;
            font-weight: 600;
            font-size: 14px;
        }
        
        td {
            padding: 12px 15px;
            border-bottom: 1px solid #e0e0e0;
            font-size: 13px;
        }
        
        tbody tr:hover {
            background-color: #f8f9fa;
        }
        
        tbody tr:last-child td {
            border-bottom: none;
        }
        
        .action-button {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            font-size: 12px;
            cursor: pointer;
            transition: all 0.3s ease;
            text-decoration: none;
            display: inline-block;
        }
        
        .action-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
        }
        
        .action-button:disabled {
            opacity: 0.8;
            cursor: not-allowed;
            transform: none;
        }
        
        .std-clickable {
            cursor: pointer;
            color: #667eea;
            text-decoration: none;
            transition: color 0.2s ease;
        }
        
        .std-clickable:hover {
            color: #764ba2;
            text-decoration: underline;
        }
        
        .empty-state {
            text-align: center;
            padding: 50px 20px;
            color: #999;
            font-size: 16px;
        }
        
        .empty-icon {
            font-size: 48px;
            margin-bottom: 15px;
        }
        
        .result-count {
            color: #666;
            font-size: 14px;
            margin-bottom: 15px;
        }
        
        .highlight {
            color: #667eea;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="container">
        <a href="/" class="nav-back">← 返回首页</a>
        
        <div class="header">
            <div class="icon">🔍</div>
            <h1>搜索标准</h1>
            <p class="subtitle">查询国家标准文档信息</p>
        </div>
        
        <div class="search-box">
            <input type="text" id="searchInput" class="search-input" placeholder="输入标准名称或标准号，如: 质量管理 或 GB/T 19001">
            <button onclick="performSearch()" id="searchBtn" class="search-button">搜索</button>
        </div>
        
        <div class="info-message" id="infoMessage"></div>
        <div class="error-message" id="errorMessage"></div>
        
        <div class="loading" id="loading">
            <div class="spinner"></div>
            <div class="spinner-text">搜索中...</div>
        </div>
        
        <div class="result-count" id="resultCount"></div>
        
        <!-- 筛选和排序区域 -->
        <div class="filter-container" id="filterContainer" style="display: none;">
            <div class="filter-item">
                <label>标准状态：</label>
                <select id="statusFilter">
                    <option value="">全部状态</option>
                    <option value="现行">现行</option>
                    <option value="废止">废止</option>
                    <option value="即将实施">即将实施</option>
                </select>
            </div>
            
            <div class="filter-item">
                <label>标准类别：</label>
                <select id="categoryFilter">
                    <option value="">全部类别</option>
                    <option value="国家标准">国家标准</option>
                    <option value="行业标准">行业标准</option>
                    <option value="地方标准">地方标准</option>
                    <option value="团体标准">团体标准</option>
                    <option value="企业标准">企业标准</option>
                </select>
            </div>
            
            <div class="filter-item">
                <label>发布年份：</label>
                <input type="number" id="yearFrom" placeholder="起始年份" min="1900" max="2030">
                <span> - </span>
                <input type="number" id="yearTo" placeholder="结束年份" min="1900" max="2030">
            </div>
            
            <div class="filter-item">
                <label>排序方式：</label>
                <select id="sortBy">
                    <option value="relevance">综合排序</option>
                    <option value="standard_num">标准号(A→Z)</option>
                    <option value="standard_name">标准名(A→Z)</option>
                    <option value="release_date">发布时间(新→旧)</option>
                    <option value="release_date_asc">发布时间(旧→新)</option>
                    <option value="year">发布年份(新→旧)</option>
                    <option value="year_asc">发布年份(旧→新)</option>
                </select>
            </div>
            
            <button onclick="applyFilters()" class="filter-button">应用筛选</button>
            <button onclick="resetFilters()" class="filter-button" style="background: #999;">重置</button>
        </div>
        
        <div class="table-wrapper" id="tableWrapper">
            <table>
                <thead>
                    <tr>
                        <th style="width: 15%;">标准号</th>
                        <th style="width: 35%;">标准名称</th>
                        <th style="width: 10%;">发布年份</th>
                        <th style="width: 10%;">状态</th>
                        <th style="width: 10%;">类别</th>
                        <th style="width: 10%;">页数</th>
                        <th style="width: 10%;">操作</th>
                    </tr>
                </thead>
                <tbody id="searchResults">
                </tbody>
            </table>
        </div>
        
        <!-- 分页控件 -->
        <div class="pagination-container" id="paginationContainer" style="display: none;">
            <div class="pagination-info">
                <span id="pageInfo"></span>
            </div>
            <div class="pagination-buttons">
                <button onclick="previousPage()" id="prevBtn" class="pagination-btn">上一页</button>
                <span id="pageNumbers" class="page-numbers"></span>
                <button onclick="nextPage()" id="nextBtn" class="pagination-btn">下一页</button>
            </div>
        </div>
        
        <div class="empty-state" id="emptyState" style="display: none;">
            <div class="empty-icon">📭📭</div>
            <p>没有找到相关标准</p>
        </div>
    </div>
    
    <script>
        const ITEMS_PER_PAGE = 50;
        let allResults = [];
        let currentPage = 1;
        let filteredResults = [];
        
        function performSearch() {
            const keyword = document.getElementById('searchInput').value.trim();
            
            if (!keyword) {
                showError('请输入搜索关键词');
                return;
            }
            
            hideError();
            document.getElementById('loading').classList.add('show');
            document.getElementById('tableWrapper').classList.remove('show');
            document.getElementById('paginationContainer').style.display = 'none';
            document.getElementById('filterContainer').style.display = 'none';
            document.getElementById('emptyState').style.display = 'none';
            
            fetch('/api/search', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({keyword: keyword})
            })
            .then(r => r.json())
            .then(data => {
                document.getElementById('loading').classList.remove('show');
                
                if (data.success) {
                    const results = data.results || [];
                    if (results.length > 0) {
                        allResults = results;
                        currentPage = 1;
                        applyFilters();
                        document.getElementById('filterContainer').style.display = 'flex';
                    } else {
                        showEmpty();
                    }
                } else {
                    showError(data.message || '搜索失败');
                }
            })
            .catch(e => {
                document.getElementById('loading').classList.remove('show');
                showError('网络错误，请检查连接');
            });
        }
        
        function applyFilters() {
            const statusFilter = document.getElementById('statusFilter').value;
            const categoryFilter = document.getElementById('categoryFilter').value;
            const yearFrom = document.getElementById('yearFrom').value;
            const yearTo = document.getElementById('yearTo').value;
            const sortBy = document.getElementById('sortBy').value;
            
            // 应用筛选
            filteredResults = allResults.filter(item => {
                // 状态筛选
                if (statusFilter && item.stan_status !== statusFilter) {
                    return false;
                }
                
                // 类别筛选
                if (categoryFilter && item.stan_category !== categoryFilter) {
                    return false;
                }
                
                // 年份范围筛选
                if (yearFrom && item.stan_year < parseInt(yearFrom)) {
                    return false;
                }
                if (yearTo && item.stan_year > parseInt(yearTo)) {
                    return false;
                }
                
                return true;
            });
            
            // 应用排序
            switch(sortBy) {
                case 'standard_num':
                    filteredResults.sort((a, b) => (a.standard_num || '').localeCompare(b.standard_num || ''));
                    break;
                case 'standard_name':
                    filteredResults.sort((a, b) => (a.standard_name || '').localeCompare(b.standard_name || ''));
                    break;
                case 'release_date':
                    filteredResults.sort((a, b) => {
                        const dateA = new Date(b.release_date || '1900-01-01');
                        const dateB = new Date(a.release_date || '1900-01-01');
                        return dateA - dateB;
                    });
                    break;
                case 'release_date_asc':
                    filteredResults.sort((a, b) => {
                        const dateA = new Date(a.release_date || '1900-01-01');
                        const dateB = new Date(b.release_date || '1900-01-01');
                        return dateA - dateB;
                    });
                    break;
                case 'year':
                    filteredResults.sort((a, b) => (b.stan_year || 0) - (a.stan_year || 0));
                    break;
                case 'year_asc':
                    filteredResults.sort((a, b) => (a.stan_year || 0) - (b.stan_year || 0));
                    break;
                case 'relevance':
                default:
                    // 保持原顺序
                    break;
            }
            
            currentPage = 1;
            displayTable();
        }
        
        function resetFilters() {
            document.getElementById('statusFilter').value = '';
            document.getElementById('categoryFilter').value = '';
            document.getElementById('yearFrom').value = '';
            document.getElementById('yearTo').value = '';
            document.getElementById('sortBy').value = 'relevance';
            applyFilters();
        }
        
        function displayTable() {
            const startIdx = (currentPage - 1) * ITEMS_PER_PAGE;
            const endIdx = startIdx + ITEMS_PER_PAGE;
            const pageResults = filteredResults.slice(startIdx, endIdx);
            
            // 显示结果统计
            const totalPages = Math.ceil(filteredResults.length / ITEMS_PER_PAGE);
            document.getElementById('resultCount').innerHTML = 
                '<span class="highlight">共 ' + filteredResults.length + '</span> 个结果，第 ' + currentPage + ' 页，共 ' + totalPages + ' 页';
            
            // 显示表格
            const tbody = document.getElementById('searchResults');
            tbody.innerHTML = '';
            
            pageResults.forEach(item => {
                const row = document.createElement('tr');
                const stdNum = item.standard_num || '';
                row.innerHTML = `
                    <td class="std-clickable" title="点击直接下载"><strong>${escapeHtml(item.standard_num || '-')}</strong></td>
                    <td class="std-clickable" title="点击直接下载">${escapeHtml(item.standard_name || '-')}</td>
                    <td>${escapeHtml(item.stan_year || '-')}</td>
                    <td>${escapeHtml(item.stan_status || '现行')}</td>
                    <td>${escapeHtml(item.stan_category || '-')}</td>
                    <td>${escapeHtml(item.page_count || '-')}</td>
                    <td><button class="action-button">下载</button></td>
                `;
                row.querySelectorAll('.std-clickable, .action-button').forEach(el => {
                    el.addEventListener('click', function(e) { e.preventDefault(); downloadStandard(stdNum, e); });
                });
                tbody.appendChild(row);
            });
            
            document.getElementById('tableWrapper').classList.add('show');
            updatePagination(totalPages);
        }
        
        function updatePagination(totalPages) {
            if (filteredResults.length === 0) {
                document.getElementById('paginationContainer').style.display = 'none';
                return;
            }
            
            // 更新上一页按钮
            document.getElementById('prevBtn').disabled = currentPage === 1;
            // 更新下一页按钮
            document.getElementById('nextBtn').disabled = currentPage === totalPages;
            
            // 生成页码按钮
            const pageNumbersDiv = document.getElementById('pageNumbers');
            pageNumbersDiv.innerHTML = '';
            
            let startPage = Math.max(1, currentPage - 2);
            let endPage = Math.min(totalPages, currentPage + 2);
            
            if (startPage > 1) {
                const btn = document.createElement('span');
                btn.textContent = '1';
                btn.className = 'page-num';
                btn.onclick = () => goToPage(1);
                pageNumbersDiv.appendChild(btn);
                
                if (startPage > 2) {
                    const dots = document.createElement('span');
                    dots.textContent = '...';
                    dots.style.padding = '6px 4px';
                    pageNumbersDiv.appendChild(dots);
                }
            }
            
            for (let i = startPage; i <= endPage; i++) {
                const btn = document.createElement('span');
                btn.textContent = i;
                btn.className = 'page-num' + (i === currentPage ? ' active' : '');
                btn.onclick = () => goToPage(i);
                pageNumbersDiv.appendChild(btn);
            }
            
            if (endPage < totalPages) {
                if (endPage < totalPages - 1) {
                    const dots = document.createElement('span');
                    dots.textContent = '...';
                    dots.style.padding = '6px 4px';
                    pageNumbersDiv.appendChild(dots);
                }
                const btn = document.createElement('span');
                btn.textContent = totalPages;
                btn.className = 'page-num';
                btn.onclick = () => goToPage(totalPages);
                pageNumbersDiv.appendChild(btn);
            }
            
            document.getElementById('paginationContainer').style.display = 'block';
            document.getElementById('pageInfo').textContent = 
                `显示 ${(currentPage - 1) * ITEMS_PER_PAGE + 1} - ${Math.min(currentPage * ITEMS_PER_PAGE, filteredResults.length)} / 共 ${filteredResults.length} 条`;
        }
        
        function previousPage() {
            if (currentPage > 1) {
                currentPage--;
                displayTable();
                window.scrollTo(0, 0);
            }
        }
        
        function nextPage() {
            const totalPages = Math.ceil(filteredResults.length / ITEMS_PER_PAGE);
            if (currentPage < totalPages) {
                currentPage++;
                displayTable();
                window.scrollTo(0, 0);
            }
        }
        
        function goToPage(pageNum) {
            currentPage = pageNum;
            displayTable();
            window.scrollTo(0, 0);
        }
        
        function showEmpty() {
            document.getElementById('emptyState').style.display = 'block';
            document.getElementById('resultCount').innerHTML = '';
        }
        
        function showError(msg) {
            const errorEl = document.getElementById('errorMessage');
            errorEl.innerHTML = msg;
            errorEl.classList.add('show');
        }
        
        function hideError() {
            document.getElementById('errorMessage').classList.remove('show');
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        function downloadStandard(standardNum, event) {
            if (event) event.preventDefault();
            const row = event && event.target ? event.target.closest('tr') : null;
            const btn = row ? row.querySelector('.action-button') : null;
            if (btn && btn.disabled) return;
            if (!standardNum || standardNum === '-') {
                showError('标准号无效');
                return;
            }
            if (btn) {
                btn.disabled = true;
                btn.textContent = '下载中...';
            }
            fetch('/api/download', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({standard_num: standardNum})
            })
            .then(r => r.json())
            .then(data => {
                if (!data.success) {
                    if (btn) { btn.disabled = false; btn.textContent = '下载'; }
                    showError(data.message || '下载失败');
                    return;
                }
                const taskId = data.task_id;
                function poll() {
                    fetch('/api/status/' + taskId)
                    .then(r => r.json())
                    .then(status => {
                        if (status.status === 'completed') {
                            if (btn) { btn.disabled = false; btn.textContent = '下载'; }
                            if (status.download_url) window.open(status.download_url, '_blank');
                        } else if (status.status === 'error') {
                            if (btn) { btn.disabled = false; btn.textContent = '下载'; }
                            showError(status.message || '下载失败');
                        } else {
                            setTimeout(poll, 1500);
                        }
                    })
                    .catch(() => {
                        if (btn) { btn.disabled = false; btn.textContent = '下载'; }
                        showError('状态查询失败');
                    });
                }
                poll();
            })
            .catch(() => {
                if (btn) { btn.disabled = false; btn.textContent = '下载'; }
                showError('网络错误，请检查连接');
            });
        }
        
        // 按回车键搜索
        document.getElementById('searchInput').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') performSearch();
        });
    </script>
</body>
</html>
'''
# 存储状态
download_status = {}
task_queue = queue.Queue()
TEMP_DIR = os.path.join(tempfile.gettempdir(), 'njbz_downloads')
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

def download_task(task_id, standard_num):
    try:
        # 创建临时目录
        task_dir = os.path.join(TEMP_DIR, task_id)
        img_dir = os.path.join(task_dir, 'images')
        os.makedirs(img_dir, exist_ok=True)
        
        # 下载图片
        download_status[task_id] = {'status': 'downloading', 'progress': 0, 'message': '正在下载...'}
        
        # 获取图片链接
        url = f'http://www.njbz365.com/njbzb/stanThumbAndCut/getAllCutPageAndUrlForRead.do?stanNum={standard_num.replace(" ", "%20")}'
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        data = response.json()
        
        if not data.get('success'):
            download_status[task_id] = {'status': 'error', 'message': '未找到标准'}
            return
        
        links = []
        for page in data['content']:
            link = page['storagePath']
            link = link.replace('zsfwsecret', '218.2.107.93')
            link = link.replace('csfwsecret', '172.17.150.27')
            link = link.replace('345687', '/document/')
            link = link.replace('456798', '/picture/')
            link = link.replace('abcdfe', '/default/')
            link = link.replace('jpg0', '.png')
            links.append(link)
        
        # 下载所有图片
        for i, link in enumerate(links):
            filename = os.path.join(img_dir, f'{str(i+1).zfill(5)}.png')
            try:
                urllib.request.urlretrieve(link, filename)
            except:
                pass
            download_status[task_id]['progress'] = int((i+1) / len(links) * 100)
        
        # 转换为PDF
        download_status[task_id] = {'status': 'converting', 'message': '正在转换为PDF...'}
        png_files = sorted(glob.glob(os.path.join(img_dir, '*.png')))
        
        if png_files:
            pdf_filename = f'{standard_num.replace("/", "")}.pdf'
            pdf_path = os.path.join(task_dir, pdf_filename)
            
            with open(pdf_path, 'wb') as f:
                f.write(img2pdf.convert(png_files))
            
            download_status[task_id] = {
                'status': 'completed',
                'filename': pdf_filename,
                'download_url': f'/download/{task_id}/{pdf_filename}'
            }
        else:
            download_status[task_id] = {'status': 'error', 'message': '没有下载到图片'}
            
    except Exception as e:
        download_status[task_id] = {'status': 'error', 'message': str(e)}

def worker():
    while True:
        task_id, standard_num = task_queue.get()
        download_task(task_id, standard_num)
        task_queue.task_done()

threading.Thread(target=worker, daemon=True).start()

@app.route('/')
def index():
    return render_template_string(HTML_MAIN)

@app.route('/download-page')
def download_page():
    return render_template_string(HTML_SIMPLE)

@app.route('/search')
def search_page():
    return render_template_string(HTML_SEARCH)

def search_standards(keyword):
    """搜索标准 - 使用多个API接口，支持多页检索"""
    results = []
    
    # 优先尝试第一个API接口 - solrData
    api_configs = [
        {
            'url': 'https://www.njbz365.com/njbzb/solrData/search.do',
            'method': 'get',
            'base_params': {
                'searchString': keyword,
                'isTilu': 'true',
                'isContent': 'true'
            },
            'result_fields': ['result', 'resultList', 'content'],
            'pagination': True,
            'start_param': 'start',
            'count_param': 'count',
            'page_size': 50,
            'max_results': 6666
        },
        {
            'url': 'https://www.njbz365.com/njbzb/memberShipManage/addSearchStringClick.do',
            'method': 'post',
            'base_params': {
                'searchString': keyword
            },
            'result_fields': ['result', 'resultList', 'content'],
            'pagination': False
        }
    ]
    
    for api_config in api_configs:
        try:
            url = api_config['url']
            
            # 如果支持分页，则进行多页检索
            if api_config.get('pagination', False):
                print(f"[开始搜索] 正在查询: {url} (支持分页)")
                start = 0
                has_more = True
                page_num = 0
                
                while has_more and len(results) < api_config.get('max_results', 6666):
                    params = api_config['base_params'].copy()
                    
                    # 第一页不需要 start 和 count 参数
                    if start > 0:
                        params[api_config['start_param']] = start
                        params[api_config['count_param']] = api_config['page_size']
                    
                    try:
                        print(f"[{url}] 获取第 {page_num + 1} 页 (start={start})...")
                        
                        if api_config['method'] == 'post':
                            response = requests.post(url, data=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10, verify=False)
                        else:
                            response = requests.get(url, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10, verify=False)
                        
                        response.raise_for_status()
                        
                        if response.text:
                            try:
                                data = response.json()
                            except ValueError:
                                print(f"[{url}] 第 {page_num} 页：响应不是有效JSON")
                                break
                            
                            success = data.get('success')
                            
                            if success is True or success == 'true':
                                items = []
                                for field_name in api_config['result_fields']:
                                    if field_name in data:
                                        items = data.get(field_name, [])
                                        break
                                
                                if not items:
                                    print(f"[{url}] 第 {page_num} 页：无数据，停止分页")
                                    has_more = False
                                    break
                                
                                print(f"[{url}] 第 {page_num} 页：找到 {len(items)} 条结果")
                                
                                # 解析每个标准项 - 增加更多字段
                                for item in items:
                                    standard_num = item.get('stdNumber') or item.get('STAN_NUM') or item.get('stanNum') or item.get('number', '')
                                    standard_name = item.get('stdName') or item.get('STAN_CNNAME') or item.get('stanName') or item.get('name', '')
                                    release_date = item.get('stdReleaseDate') or item.get('PUB_DATE') or item.get('releaseDate') or item.get('date', '')
                                    status = item.get('stdStatus') or item.get('STAN_STATUS') or item.get('stanStatus') or item.get('status', '现行')
                                    category = item.get('STAN_CATEGORY') or item.get('stanCategory') or item.get('category', '')
                                    year = item.get('STAN_PART_YEAR') or item.get('stanYear') or item.get('year', '')
                                    page_count = item.get('PAGE_COUNT') or item.get('pageCount') or item.get('pages', '')
                                    
                                    # 清除HTML标签
                                    standard_name = strip_html_tags(standard_name)
                                    # 格式化发布日期
                                    release_date = format_release_date(release_date)
                                    status = strip_html_tags(status)
                                    category = strip_html_tags(category)
                                    
                                    if standard_num:  # 只添加有标准号的结果
                                        results.append({
                                            'standard_num': standard_num,
                                            'standard_name': standard_name,
                                            'release_date': release_date,
                                            'status': status,
                                            'stan_status': status,  # 用于筛选
                                            'stan_category': category,  # 用于筛选
                                            'stan_year': int(year) if year and str(year).isdigit() else None,  # 用于筛选
                                            'page_count': page_count  # 页数信息
                                        })
                                
                                # 如果这页数据不足页面大小，说明到底了
                                if len(items) < api_config['page_size']:
                                    has_more = False
                                    print(f"[{url}] 已到末页，共获取 {len(results)} 条结果")
                                else:
                                    # 准备下一页
                                    start += api_config['page_size']
                                    page_num += 1
                            else:
                                error_msg = data.get('message') or data.get('msg') or data.get('errMsg') or str(data)
                                print(f"[{url}] 第 {page_num} 页错误: {error_msg}")
                                has_more = False
                    
                    except requests.exceptions.RequestException as e:
                        print(f"[{url}] 第 {page_num} 页网络请求失败: {e}")
                        has_more = False
                    except Exception as e:
                        print(f"[{url}] 第 {page_num} 页出错: {type(e).__name__}: {e}")
                        has_more = False
                
                if results:
                    print(f"[成功] {url} 共搜索到 {len(results)} 个结果")
                    return results
            
            else:
                # 非分页API
                print(f"[开始搜索] 正在查询: {url}")
                params = api_config['base_params']
                
                if api_config['method'] == 'post':
                    response = requests.post(url, data=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10, verify=False)
                else:
                    response = requests.get(url, params=params, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10, verify=False)
                
                response.raise_for_status()
                
                if response.text:
                    try:
                        data = response.json()
                    except ValueError:
                        print(f"[{url}] 响应不是有效JSON，原始内容: {response.text[:200]}")
                        continue
                    
                    print(f"[{url}] API响应success: {data.get('success')}")
                    
                    success = data.get('success')
                    
                    if success is True or success == 'true':
                        items = []
                        for field_name in api_config['result_fields']:
                            if field_name in data:
                                items = data.get(field_name, [])
                                print(f"[{url}] 从字段 '{field_name}' 找到 {len(items)} 条结果")
                                break
                        
                        # 解析每个标准项 - 增加更多字段
                        for item in items:
                            standard_num = item.get('stdNumber') or item.get('STAN_NUM') or item.get('stanNum') or item.get('number', '')
                            standard_name = item.get('stdName') or item.get('STAN_CNNAME') or item.get('stanName') or item.get('name', '')
                            release_date = item.get('stdReleaseDate') or item.get('PUB_DATE') or item.get('releaseDate') or item.get('date', '')
                            status = item.get('stdStatus') or item.get('STAN_STATUS') or item.get('stanStatus') or item.get('status', '现行')
                            category = item.get('STAN_CATEGORY') or item.get('stanCategory') or item.get('category', '')
                            year = item.get('STAN_PART_YEAR') or item.get('stanYear') or item.get('year', '')
                            page_count = item.get('PAGE_COUNT') or item.get('pageCount') or item.get('pages', '')
                            
                            # 清除HTML标签
                            standard_name = strip_html_tags(standard_name)
                            # 格式化发布日期
                            release_date = format_release_date(release_date)
                            status = strip_html_tags(status)
                            category = strip_html_tags(category)
                            
                            if standard_num:  # 只添加有标准号的结果
                                results.append({
                                    'standard_num': standard_num,
                                    'standard_name': standard_name,
                                    'release_date': release_date,
                                    'status': status,
                                    'stan_status': status,  # 用于筛选
                                    'stan_category': category,  # 用于筛选
                                    'stan_year': int(year) if year and str(year).isdigit() else None,  # 用于筛选
                                    'page_count': page_count  # 页数信息
                                })
                        
                        if results:
                            print(f"[成功] {url} 搜索到 {len(results)} 个结果")
                            return results
                        else:
                            print(f"[{url}] success=True但无有效数据")
                    else:
                        error_msg = data.get('message') or data.get('msg') or data.get('errMsg') or str(data)
                        print(f"[{url}] API返回: {error_msg}")
        
        except requests.exceptions.RequestException as e:
            print(f"[{url}] 网络请求失败: {e}")
            continue
        except Exception as e:
            print(f"[{url}] 出错: {type(e).__name__}: {e}")
            continue
    
    # 如果没找到，返回空列表
    print(f"[搜索完成] 未找到与'{keyword}'相匹配的标准")
    return results
@app.route('/api/search', methods=['POST'])
def api_search():
    data = request.json
    keyword = data.get('keyword', '').strip()
    
    if not keyword:
        return jsonify({'success': False, 'message': '请输入搜索关键词'})
    
    results = search_standards(keyword)
    
    if not results:
        return jsonify({
            'success': True, 
            'results': [],
            'message': f'未找到与"{keyword}"相关的标准。请尝试其他关键词。'
        })
    
    return jsonify({'success': True, 'results': results})

@app.route('/api/download', methods=['POST'])
def start_download():
    data = request.json
    standard_num = data.get('standard_num', '').strip()
    
    if not standard_num:
        return jsonify({'success': False, 'message': '请输入标准号'})
    
    task_id = str(uuid.uuid4())
    download_status[task_id] = {'status': 'pending', 'message': '等待中...'}
    task_queue.put((task_id, standard_num))
    
    return jsonify({'success': True, 'task_id': task_id})

@app.route('/api/status/<task_id>')
def get_status(task_id):
    return jsonify(download_status.get(task_id, {'status': 'not_found'}))

@app.route('/download/<task_id>/<filename>')
def download_file(task_id, filename):
    file_path = os.path.join(TEMP_DIR, task_id, filename)
    if os.path.exists(file_path):
        return send_file(file_path, as_attachment=True)
    return jsonify({'error': '文件不存在'}), 404

if __name__ == '__main__':
    print("标准下载器已启动!")
    print("访问: http://127.0.0.1:5000")
    app.run(debug=True, port=5000, use_reloader=False)