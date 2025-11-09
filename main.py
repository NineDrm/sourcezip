from fastapi import FastAPI, HTTPException, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
import requests
import base64
import os
import random
import string
import json
from datetime import datetime
import re

app = FastAPI(title="GitHub文件上传API")

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def generate_random_string(length: int = 8) -> str:
    return ''.join(random.choices(string.ascii_letters, k=length))

def process_json_content(file_content: bytes):
    """
    处理JSON内容，确保被一个[]包裹
    返回处理后的内容和文件类型
    """
    try:
        # 解析JSON
        file_json = json.loads(file_content)
        
        # 确定文件类型和名称字段
        file_type = None
        name_field = None
        name_value = None
        
        if isinstance(file_json, dict):
            # 单个对象
            if "bookSourceName" in file_json:
                file_type = "book_source"
                name_field = "bookSourceName"
                name_value = file_json.get("bookSourceName")
            elif "sourceName" in file_json:
                file_type = "subscription_source" 
                name_field = "sourceName"
                name_value = file_json.get("sourceName")
            else:
                raise ValueError("JSON中未找到bookSourceName或sourceName字段")
                
            # 确保被[]包裹
            processed_json = [file_json]
            
        elif isinstance(file_json, list):
            # 数组，检查第一个元素
            if len(file_json) == 0:
                raise ValueError("JSON数组为空")
                
            first_item = file_json[0]
            if isinstance(first_item, dict):
                if "bookSourceName" in first_item:
                    file_type = "book_source"
                    name_field = "bookSourceName"
                    name_value = first_item.get("bookSourceName")
                elif "sourceName" in first_item:
                    file_type = "subscription_source"
                    name_field = "sourceName" 
                    name_value = first_item.get("sourceName")
                else:
                    raise ValueError("JSON数组中未找到bookSourceName或sourceName字段")
            else:
                raise ValueError("JSON数组中的元素不是对象")
            
            # 确保被一个[]包裹（已经是数组，不需要处理）
            processed_json = file_json
            
        else:
            raise ValueError("JSON格式不正确")
        
        # 清理文件名中的非法字符
        if name_value:
            name_value = re.sub(r'[\\/*?:"<>|]', '', name_value)
            name_value = name_value.strip()
        
        # 重新编码为JSON字符串
        processed_content = json.dumps(processed_json, ensure_ascii=False, indent=2)
        
        return processed_content.encode('utf-8'), file_type, name_field, name_value
        
    except json.JSONDecodeError:
        raise ValueError("上传的文件不是有效的JSON格式")
    except Exception as e:
        raise ValueError(f"处理JSON内容时出错: {str(e)}")

def get_folder_name(file_type):
    """根据文件类型返回文件夹名称"""
    if file_type == "book_source":
        return "book-sources"
    elif file_type == "subscription_source":
        return "subscription-sources"
    else:
        return "others"

@app.post("/upload")
async def upload_file_to_github(
    repo_name: str = Form(...),
    branch: str = Form(...),
    commit_message: str = Form(...),
    access_token: str = Form(...),
    file: UploadFile = File(...)
):
    """
    上传文件到GitHub仓库，返回文件路径（直链）
    """
    try:
        # 读取文件内容
        file_content = await file.read()
        
        if not file_content:
            raise HTTPException(status_code=400, detail="文件内容为空")
        
        # 处理JSON内容
        processed_content, file_type, name_field, name_value = process_json_content(file_content)
        
        if not name_value:
            raise HTTPException(status_code=400, detail="无法从JSON中提取名称")
        
        # 根据文件类型确定文件夹和文件名
        folder_name = get_folder_name(file_type)
        file_name = f"{name_value}.json"
        file_path = f"{folder_name}/{file_name}"
        
        # GitHub API配置
        base_url = f"https://api.github.com/repos/{repo_name}/contents/{file_path}"
        
        headers = {
            "Authorization": f"token {access_token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "FastAPI-Uploader"
        }
        
        # 检查文件是否存在
        response = requests.get(base_url, headers=headers)
        
        # 准备上传数据
        data = {
            "message": commit_message,
            "content": base64.b64encode(processed_content).decode('utf-8'),
            "branch": branch
        }
        
        # 如果文件已存在，需要提供sha
        if response.status_code == 200:
            file_info = response.json()
            data["sha"] = file_info["sha"]
        
        # 上传文件到GitHub（使用PUT方法）
        upload_response = requests.put(base_url, headers=headers, json=data)
        
        if upload_response.status_code in [201, 200]:
            # 返回文件相对路径（直链路径）
            return file_path
            
        else:
            error_msg = f"文件上传失败"
            try:
                error_detail = upload_response.json()
                error_msg += f": {error_detail.get('message', '未知错误')}"
            except:
                error_msg += f"，状态码: {upload_response.status_code}"
            
            raise HTTPException(status_code=400, detail=error_msg)
            
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"服务器内部错误: {str(e)}")

@app.post("/upload-simple")
async def upload_file_simple(
    file: UploadFile = File(...),
    repo_name: str = Form(default="NineDrm/sourcezip"),
    branch: str = Form(default="main"),
    commit_message: str = Form(default="上传书源文件"),
    access_token: str = Form(...)
):
    """
    简化版上传接口 - 返回阅读APP期望的格式
    """
    try:
        file_path = await upload_file_to_github(
            repo_name=repo_name,
            branch=branch,
            commit_message=commit_message,
            access_token=access_token,
            file=file
        )
        
        # 返回阅读APP期望的成功格式
        return {
            "message": "ok",
            "data": file_path  # 文件路径，如 "book-sources/NOYACG.json"
        }
        
    except HTTPException as e:
        # 返回错误格式
        return {
            "message": "error",
            "data": f"上传失败: {e.detail}"
        }

@app.get("/")
async def root():
    return {
        "message": "GitHub文件上传服务正常运行",
        "deployed_on": "Vercel",
        "usage": {
            "简化上传": "POST /upload-simple",
            "返回格式": "符合阅读APP标准的JSON格式"
        }
    }

# Vercel需要这个
app = app
