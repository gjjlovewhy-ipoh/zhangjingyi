#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
from bs4 import BeautifulSoup
import re
import time
import os
from datetime import datetime
from pathlib import Path
import logging
from urllib.parse import urlparse

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 配置
BASE_URL = "http://120.76.248.139/udp/txiptv_iplist.php"
DEVICE_ID = "5b59b24e74886da42d969c7c6e09729b"
OUTPUT_FILE = "iptv_sources.txt"
M3U_OUTPUT_FILE = "iptv_sources.m3u"
LOG_FILE = "crawler.log"

class IPTVCrawler:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.channels = []  # 存储 (频道名, 地址) 元组
        self.timeout = 10
        
    def fetch_page(self, url):
        """获取页面内容"""
        try:
            response = self.session.get(url, timeout=self.timeout)
            response.encoding = 'utf-8'
            return response.text
        except requests.exceptions.Timeout:
            logger.error(f"请求超时: {url}")
            return None
        except requests.exceptions.ConnectionError:
            logger.error(f"连接错误: {url}")
            return None
        except Exception as e:
            logger.error(f"获取页面失败 {url}: {e}")
            return None
    
    def extract_custom_interface_ips(self, html_content):
        """从主页面提取所有自定义接口的IP:端口"""
        ips = []
        
        # 正则提取IP:端口的模式
        ip_patterns = re.findall(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}):(\d+)', html_content)
        
        for ip, port in ip_patterns:
            ip_port = f"{ip}:{port}"
            if ip_port not in ips:
                ips.append(ip_port)
        
        logger.info(f"找到 {len(ips)} 个自定义接口IP:端口")
        return ips
    
    def parse_channels_from_page(self, html_content):
        """从页面提取频道名和地址对"""
        channels = []
        
        # 移除所有 <br> 标签
        content = html_content.replace('<br>', '\n').replace('<BR>', '\n')
        content = re.sub(r'<[^>]+>', '', content)  # 移除所有HTML标签
        
        # 按行分割
        lines = content.strip().split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # 跳过空行和注释
            if not line or line.startswith('#') or line.startswith('//'):
                i += 1
                continue
            
            # 检查是否是URL（可能是地址）
            if line.startswith('http://') or line.startswith('https://') or line.startswith('rtmp'):
                # 如果当前行是URL，使用上一行作为频道名
                if i > 0:
                    prev_line = lines[i-1].strip()
                    if prev_line and not prev_line.startswith('#') and not (prev_line.startswith('http') or prev_line.startswith('rtmp')):
                        channel_name = prev_line
                        address = line
                        channels.append((channel_name, address))
                        i += 1
                        continue
                
                # 否则从URL中提取频道名
                parsed = urlparse(line)
                channel_name = parsed.path.split('/')[-1] or 'Channel'
                channels.append((channel_name, line))
                i += 1
                continue
            
            # 如果当前行不是URL，检查下一行是否是URL
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                if next_line.startswith('http://') or next_line.startswith('https://') or next_line.startswith('rtmp'):
                    # 当前行作为频道名，下一行作为地址
                    channel_name = line
                    address = next_line
                    channels.append((channel_name, address))
                    i += 2
                    continue
            
            i += 1
        
        return channels
    
    def crawl(self):
        """主爬虫流程"""
        logger.info("="*70)
        logger.info(f"开始爬虫任务 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info("="*70)
        
        self.channels = []
        
        # 1. 获取主页面（包含自定义接口列表）
        main_url = f"{BASE_URL}?deviceId={DEVICE_ID}"
        logger.info(f"正在获取主页面: {main_url}")
        main_html = self.fetch_page(main_url)
        
        if not main_html:
            logger.error("无法获取主页面")
            return False
        
        logger.info(f"主页面大小: {len(main_html)} 字节")
        
        # 2. 从主页面提取所有自定义接口的IP:端口
        interface_ips = self.extract_custom_interface_ips(main_html)
        
        if not interface_ips:
            logger.error("未找到自定义接口IP:端口")
            return False
        
        logger.info(f"找到 {len(interface_ips)} 个自定义接口")
        
        # 3. 逐个访问每个自定义接口获取频道信息
        logger.info(f"开始处理自定义接口...")
        for idx, ip_port in enumerate(interface_ips, 1):
            # 构建完整URL
            custom_url = f"http://120.76.248.139/udp/txiptv_chlist_zdy.php?deviceId={DEVICE_ID}&ip={ip_port}"
            logger.info(f"[{idx}/{len(interface_ips)}] 正在处理: {custom_url}")
            
            try:
                page_html = self.fetch_page(custom_url)
                
                if page_html:
                    # 提取频道名和地址对
                    channels = self.parse_channels_from_page(page_html)
                    self.channels.extend(channels)
                    logger.info(f"  ✓ 找到 {len(channels)} 个频道")
                else:
                    logger.warning(f"  ✗ 页面获取失败")
                
            except Exception as e:
                logger.error(f"  ✗ 处理失败: {e}")
            
            # 礼貌的延迟，避免请求过快
            time.sleep(0.5)
        
        # 4. 去重（基于地址）
        original_count = len(self.channels)
        seen_addresses = set()
        unique_channels = []
        for name, addr in self.channels:
            if addr not in seen_addresses:
                seen_addresses.add(addr)
                unique_channels.append((name, addr))
        
        self.channels = unique_channels
        logger.info(f"去重处理: {original_count} -> {len(self.channels)} 个频道")
        
        # 5. 保存结果
        success = self.save_results()
        
        logger.info("="*70)
        if success:
            logger.info("✓ 爬虫任务完成")
        else:
            logger.error("✗ 爬虫任务完成，但保存失败")
        logger.info("="*70)
        
        return success
    
    def save_results(self):
        """保存结果到文件"""
        success = True
        
        # 保存为 TV Box 播放源格式 (.txt)
        try:
            with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
                f.write("iptv,#genre#\n")
                for channel_name, address in self.channels:
                    f.write(f"{channel_name},{address}\n")
            
            file_size = os.path.getsize(OUTPUT_FILE)
            logger.info(f"✓ 已保存到 {OUTPUT_FILE} ({file_size} 字节，共 {len(self.channels)} 个频道)")
        except Exception as e:
            logger.error(f"✗ 保存文本文件失败: {e}")
            success = False
        
        # 保存为 M3U 格式
        try:
            with open(M3U_OUTPUT_FILE, 'w', encoding='utf-8') as f:
                f.write("#EXTM3U\n")
                for channel_name, address in self.channels:
                    f.write(f"#EXTINF:-1 group-title=\"iptv\",{channel_name}\n")
                    f.write(f"{address}\n")
            
            file_size = os.path.getsize(M3U_OUTPUT_FILE)
            logger.info(f"✓ 已保存M3U格式到 {M3U_OUTPUT_FILE} ({file_size} 字节，共 {len(self.channels)} 个频道)")
        except Exception as e:
            logger.error(f"✗ 保存M3U文件失败: {e}")
            success = False
        
        return success

def main():
    """主函数"""
    try:
        crawler = IPTVCrawler()
        result = crawler.crawl()
        
        # 记录日志到文件
        with open(LOG_FILE, 'a', encoding='utf-8') as log:
            log.write(f"\n{'='*70}\n")
            log.write(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            log.write(f"结果: {'成功' if result else '失败'}\n")
            log.write(f"获取频道数: {len(crawler.channels)}\n")
        
        return 0 if result else 1
    except Exception as e:
        logger.error(f"未预期的错误: {e}", exc_info=True)
        return 1

if __name__ == "__main__":
    exit(main())
