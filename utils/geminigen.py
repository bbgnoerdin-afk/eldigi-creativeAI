import requests
import time
import json
import asyncio
import random
import string
import secrets

def get_video_token_sync():
    """Mengaktifkan dan mengambil Token Akses dari API GeminiGen"""
    url = "https://api.geminigen.ai/mobile/v1/uuid/activate-account"
    
    chars = string.ascii_letters + string.digits + "_-"
    device_token = ''.join(random.choices(chars[:62], k=22)) + ':' + ''.join(random.choices(chars, k=140))
    
    for attempt in range(10): 
        try:
            headers = {
                "user-agent": "Dart/3.10 (dart:io)", 
                "accept": "application/json",
                "accept-encoding": "gzip",
                "host": "api.geminigen.ai",
                "x-timestamp": str(int(time.time())), 
                "x-token": secrets.token_hex(16), 
                "content-type": "application/json"
            }
            
            payload = {
                "mobile_device_uuid": secrets.token_hex(8), 
                "platform": "GenV-APP",
                "device_token": device_token, 
                "device_type": "android"
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=15)
            response.raise_for_status() 
            return response.json().get("access_token")
            
        except requests.exceptions.RequestException as e:
            time.sleep(2)
        except Exception as e:
            print(f"[!] Error Token: {repr(e)}")
            return None
            
    return None

def get_geminigen_image_sync(prompt, token, img_bytes=None, img_name=None):
    """Fungsi submit task Image Generation langsung via GeminiGen (Mendukung T2I & I2I)"""
    url = "https://api.geminigen.ai/mobile/v1/generate_image"
    
    for attempt in range(10):
        try:
            headers = {
                "user-agent": "Dart/3.10 (dart:io)",
                "accept": "application/json",
                "accept-encoding": "gzip",
                "authorization": f"Bearer {token}"
            }
            
            data_payload = {
                "prompt": prompt,
                "model": "nano-banana-pro",
                "aspect_ratio": "9:16",
                "output_format": "jpg",
                "resolution": "1K"
            }
            
            # Jika ada gambar (I2I), kirim files payload
            if img_bytes and img_name:
                files_payload = [("files", (img_name, img_bytes, "image/jpeg"))]
                response = requests.post(url, headers=headers, data=data_payload, files=files_payload, timeout=30)
            else:
                # Jika tidak ada gambar (T2I), kirim data payload saja
                response = requests.post(url, headers=headers, data=data_payload, timeout=30)
                
            response.raise_for_status()
            
            return response.json().get('uuid'), None
            
        except requests.exceptions.RequestException as e:
            time.sleep(3)
        except Exception as e:
            return None, str(e)
            
    return None, "Gagal terhubung API Image setelah 10x percobaan."

def get_geminigen_task_sync(p, t, images, m, r, veo_mode=None):
    for attempt in range(10): 
        try:
            headers = {
                "user-agent": "Dart/3.10 (dart:io)",
                "accept": "application/json",
                "accept-encoding": "gzip",
                "host": "api.geminigen.ai",
                "authorization": f"Bearer {t}"
            }

            if m in ["veo_fast", "veo_lite"]:
                model_payload = "veo-3.1-fast" if m == "veo_fast" else "veo-3.1-lite"
                url = "https://api.geminigen.ai/mobile/v3/video-gen"
                data_payload = {
                    "prompt": p,
                    "model": model_payload,
                    "duration": "8",
                    "resolution": "1080p",
                    "aspect_ratio": r,
                    "service_mode": "stable"
                }
                
                # Cek jika ada gambar (I2V) atau kosong (T2V)
                if images and len(images) > 0:
                    files_payload = [("image", (img['name'], img['bytes'], "image/jpeg")) for img in images]
                    response = requests.post(url, headers=headers, data=data_payload, files=files_payload, timeout=30)
                else:
                    # T2V tidak mengirimkan payload files
                    response = requests.post(url, headers=headers, data=data_payload, timeout=30)
                    
                response.raise_for_status()
                return response.json().get('uuid'), None

            elif m == "grok":
                url = "https://api.geminigen.ai/mobile/v3/video-gen/grok-stream"
                data_payload = {
                    "mode": "custom",
                    "prompt": p,
                    "model": "grok-video",
                    "resolution": "720p",
                    "aspect_ratio": r,
                    "duration": "10",
                    "turnstile_token": "string",
                    "service_mode": "stable"
                }
                
                # Cek jika ada gambar (I2V) atau kosong (T2V)
                if images and len(images) > 0:
                    files_payload = [("files", (img['name'], img['bytes'], "image/jpeg")) for img in images]
                    response = requests.post(url, headers=headers, data=data_payload, files=files_payload, stream=True, timeout=30)
                else:
                    # T2V tidak mengirimkan payload files
                    response = requests.post(url, headers=headers, data=data_payload, stream=True, timeout=30)
                
                response.raise_for_status()
                
                for line in response.iter_lines():
                    if line:
                        decoded_line = line.decode('utf-8')
                        if decoded_line.startswith("data: "):
                            decoded_line = decoded_line[6:]
                        try:
                            json_data = json.loads(decoded_line)
                            history_uuid = json_data.get("history_uuid")
                            if history_uuid:
                                return history_uuid, None
                        except json.JSONDecodeError:
                            continue
                raise requests.exceptions.ConnectionError("Stream terputus")
        except requests.exceptions.RequestException as e:
            time.sleep(3)
        except Exception as e:
            return None, str(e)
            
    return None, "Gagal terhubung API setelah 10x percobaan."

def geminigen_check_status_sync(access_token, video_uuid):
    url = f"https://api.geminigen.ai/mobile/v1/history/{video_uuid}"
    headers = {
        "user-agent": "Dart/3.10 (dart:io)",
        "accept": "application/json",
        "accept-encoding": "gzip",
        "authorization": f"Bearer {access_token}",
        "host": "api.geminigen.ai"
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        return response.json()
    except:
        return None

async def poll_geminigen_task(uuid, t, is_image=False):
    """Polling status task GeminiGen, bisa untuk image maupun video"""
    for _ in range(60): 
        await asyncio.sleep(10)
        data = await asyncio.to_thread(geminigen_check_status_sync, t, uuid)
        if data:
            status = data.get("status")
            if status == 2:
                if is_image:
                    imgs = data.get("generated_image", [])
                    if imgs and len(imgs) > 0:
                        return "success", imgs[0].get("image_url")
                else:
                    vids = data.get("generated_video", [])
                    if vids and len(vids) > 0:
                        return "success", vids[0].get("video_url")
            elif status in [3, 4, -1]: 
                return "failed", data.get("error_message")
    return "timeout", None