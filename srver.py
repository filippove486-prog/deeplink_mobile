#!/usr/bin/env python3
"""
Deeplink Messenger - Полный сервер на FastAPI + WebSocket
Автоматический вход, сохранение данных, AI-бот, каналы, карточки сообщений.
"""

import json
import uuid
import asyncio
import secrets
from datetime import datetime
from typing import Dict, List, Optional
from enum import Enum

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import aiosqlite
import uvicorn

# ========== МОДЕЛИ ДАННЫХ ==========
class MessageType(str, Enum):
    TEXT = "text"
    TASK = "task"
    POLL = "poll"
    LINK = "link"
    CODE = "code"

class User(BaseModel):
    id: str
    username: str
    token: str
    avatar: str = "👤"
    online: bool = False

class Message(BaseModel):
    id: str
    type: MessageType
    content: str
    sender_id: str
    channel_id: str
    timestamp: str
    metadata: dict = {}
    reactions: Dict[str, List[str]] = {}

class Channel(BaseModel):
    id: str
    name: str
    type: str = "chat"
    members: List[str] = []
    settings: dict = {}

# ========== ЯДРО СЕРВЕРА ==========
class DeeplinkServer:
    def __init__(self):
        self.app = FastAPI(title="Deeplink Messenger")
        self.active_connections: Dict[str, WebSocket] = {}
        self.users: Dict[str, User] = {}
        self.channels: Dict[str, Channel] = {}
        self.messages: Dict[str, List[Message]] = {}
        self.db = None
        
        # Создаём системные каналы
        self._create_default_channels()
        
        # Настраиваем маршруты
        self.setup_routes()
    
    def _create_default_channels(self):
        """Создаём начальные каналы"""
        general = Channel(
            id="general",
            name="📢 Общий чат",
            type="chat",
            members=[]
        )
        self.channels["general"] = general
        self.messages["general"] = []
        
        tasks = Channel(
            id="tasks",
            name="✅ Задачи",
            type="kanban",
            members=[]
        )
        self.channels["tasks"] = tasks
        self.messages["tasks"] = []
        
        media = Channel(
            id="media",
            name="🖼️ Медиа",
            type="media",
            members=[]
        )
        self.channels["media"] = media
        self.messages["media"] = []
    
    def setup_routes(self):
        """Настраиваем все endpoint'ы"""
        
        @self.app.get("/")
        async def get_frontend():
            return FileResponse("deeplink_client.html")
        
        @self.app.post("/api/register")
        async def register(request: Request):
            data = await request.json()
            username = data.get("username", "").strip()
            
            if not username:
                raise HTTPException(400, "Имя пользователя обязательно")
            
            # Проверяем, существует ли пользователь
            for user in self.users.values():
                if user.username.lower() == username.lower():
                    # Возвращаем существующего пользователя
                    return {
                        "user": user.dict(),
                        "message": "Автоматический вход выполнен"
                    }
            
            # Создаём нового пользователя
            user_id = str(uuid.uuid4())[:8]
            token = secrets.token_hex(16)
            
            user = User(
                id=user_id,
                username=username,
                token=token,
                avatar=["👤", "👨", "👩", "🐱", "🦊", "🐶", "🦁"][len(self.users) % 7]
            )
            
            self.users[user_id] = user
            
            # Добавляем во все каналы
            for channel_id in self.channels:
                if user_id not in self.channels[channel_id].members:
                    self.channels[channel_id].members.append(user_id)
            
            return {
                "user": user.dict(),
                "message": "Регистрация успешна"
            }
        
        @self.app.post("/api/login")
        async def login(request: Request):
            data = await request.json()
            user_id = data.get("user_id")
            token = data.get("token")
            
            if user_id in self.users and self.users[user_id].token == token:
                user = self.users[user_id]
                user.online = True
                return {"user": user.dict(), "success": True}
            
            raise HTTPException(401, "Ошибка входа")
        
        @self.app.get("/api/channels")
        async def get_channels():
            return {
                "channels": [c.dict() for c in self.channels.values()],
                "users": [u.dict() for u in self.users.values() if u.online]
            }
        
        @self.app.get("/api/messages/{channel_id}")
        async def get_channel_messages(channel_id: str, limit: int = 50):
            if channel_id not in self.messages:
                raise HTTPException(404, "Канал не найден")
            return self.messages[channel_id][-limit:]
        
        @self.app.post("/api/channels/create")
        async def create_channel(request: Request):
            data = await request.json()
            name = data.get("name", "Новый канал").strip()
            channel_type = data.get("type", "chat")
            
            if not name:
                raise HTTPException(400, "Название канала обязательно")
            
            channel_id = str(uuid.uuid4())[:8]
            channel = Channel(
                id=channel_id,
                name=name,
                type=channel_type,
                members=list(self.users.keys())
            )
            
            self.channels[channel_id] = channel
            self.messages[channel_id] = []
            
            # Уведомляем всех о новом канале
            await self.broadcast_system_message(f"Создан новый канал: {name}")
            
            return {"channel": channel.dict(), "success": True}
        
        @self.app.post("/api/message/send")
        async def send_message(request: Request):
            data = await request.json()
            
            message = Message(
                id=str(uuid.uuid4()),
                type=MessageType(data.get("type", "text")),
                content=data["content"],
                sender_id=data["sender_id"],
                channel_id=data["channel_id"],
                timestamp=datetime.now().strftime("%H:%M"),
                metadata=data.get("metadata", {})
            )
            
            if message.channel_id not in self.messages:
                self.messages[message.channel_id] = []
            
            self.messages[message.channel_id].append(message)
            
            # Обработка специальных типов сообщений
            if message.type == MessageType.TASK:
                message.metadata["completed"] = False
                message.metadata["completed_by"] = None
            
            elif message.type == MessageType.POLL:
                if "options" not in message.metadata:
                    message.metadata["options"] = ["Да", "Нет"]
                message.metadata["votes"] = {}
            
            elif message.type == MessageType.LINK:
                # Автоматическое создание превью для ссылок
                if message.content.startswith(("http://", "https://")):
                    message.metadata["preview"] = True
                    message.metadata["title"] = f"Ссылка от {self.users[message.sender_id].username}"
                    message.metadata["description"] = "Нажмите для перехода"
            
            # AI-ответ для сообщений с вопросом
            if "?" in message.content and message.channel_id == "general":
                asyncio.create_task(self.send_ai_response(message))
            
            # Рассылаем сообщение всем подключённым
            await self.broadcast_message(message)
            
            return {"success": True, "message_id": message.id}
        
        @self.app.post("/api/message/react")
        async def react_to_message(request: Request):
            data = await request.json()
            message_id = data["message_id"]
            channel_id = data["channel_id"]
            user_id = data["user_id"]
            emoji = data["emoji"]
            
            for msg in self.messages.get(channel_id, []):
                if msg.id == message_id:
                    if emoji not in msg.reactions:
                        msg.reactions[emoji] = []
                    if user_id not in msg.reactions[emoji]:
                        msg.reactions[emoji].append(user_id)
                    
                    await self.broadcast_reaction(msg)
                    return {"success": True}
            
            raise HTTPException(404, "Сообщение не найдено")
        
        @self.app.post("/api/message/update")
        async def update_message(request: Request):
            data = await request.json()
            message_id = data["message_id"]
            channel_id = data["channel_id"]
            action = data["action"]
            user_id = data.get("user_id")
            
            for msg in self.messages.get(channel_id, []):
                if msg.id == message_id:
                    if action == "complete_task" and msg.type == MessageType.TASK:
                        msg.metadata["completed"] = True
                        msg.metadata["completed_by"] = user_id
                    
                    elif action == "vote" and msg.type == MessageType.POLL:
                        option = data["option"]
                        votes = msg.metadata.get("votes", {})
                        votes[user_id] = option
                        msg.metadata["votes"] = votes
                    
                    await self.broadcast_message(msg)
                    return {"success": True}
            
            raise HTTPException(404, "Сообщение не найдено")
        
        @self.app.post("/api/ai/summarize")
        async def summarize_chat(request: Request):
            """AI-резюме чата"""
            data = await request.json()
            channel_id = data["channel_id"]
            
            if channel_id not in self.messages or len(self.messages[channel_id]) < 3:
                return {"summary": "Недостаточно сообщений для анализа"}
            
            last_messages = self.messages[channel_id][-10:]
            topics = set()
            participants = set()
            
            for msg in last_messages:
                participants.add(self.users.get(msg.sender_id, User(id="", username="", token="")).username)
                # Простой анализ ключевых слов
                if any(word in msg.content.lower() for word in ["задача", "сделать", "нужно"]):
                    topics.add("задачи")
                if any(word in msg.content.lower() for word in ["вопрос", "почему", "как"]):
                    topics.add("вопросы")
                if any(word in msg.content.lower() for word in ["идея", "предложение"]):
                    topics.add("идеи")
            
            summary = (
                f"📊 За последние сообщения участвовали: {', '.join(participants)}. "
                f"Обсуждаемые темы: {', '.join(topics) if topics else 'разные темы'}. "
                f"Всего сообщений в канале: {len(self.messages[channel_id])}."
            )
            
            return {"summary": summary}
        
        @self.app.websocket("/ws/{user_id}")
        async def websocket_endpoint(websocket: WebSocket, user_id: str):
            await websocket.accept()
            self.active_connections[user_id] = websocket
            
            if user_id in self.users:
                self.users[user_id].online = True
            
            try:
                while True:
                    data = await websocket.receive_json()
                    # Обработка WebSocket-команд
                    if data.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                    
            except WebSocketDisconnect:
                if user_id in self.active_connections:
                    del self.active_connections[user_id]
                if user_id in self.users:
                    self.users[user_id].online = False
    
    async def broadcast_message(self, message: Message):
        """Отправить сообщение всем подключённым пользователям"""
        message_dict = message.dict()
        message_dict["sender_name"] = self.users.get(message.sender_id, User(id="", username="Неизвестный", token="")).username
        message_dict["sender_avatar"] = self.users.get(message.sender_id, User(id="", username="", token="")).avatar
        
        for user_id, ws in self.active_connections.items():
            try:
                await ws.send_json({
                    "type": "new_message",
                    "message": message_dict
                })
            except:
                pass
    
    async def broadcast_reaction(self, message: Message):
        """Отправить обновление реакций"""
        for user_id, ws in self.active_connections.items():
            try:
                await ws.send_json({
                    "type": "message_updated",
                    "message_id": message.id,
                    "channel_id": message.channel_id,
                    "reactions": message.reactions,
                    "metadata": message.metadata
                })
            except:
                pass
    
    async def broadcast_system_message(self, text: str):
        """Отправить системное сообщение"""
        system_msg = Message(
            id=str(uuid.uuid4()),
            type=MessageType.TEXT,
            content=f"🔔 {text}",
            sender_id="system",
            channel_id="general",
            timestamp=datetime.now().strftime("%H:%M"),
            metadata={"system": True}
        )
        
        self.messages["general"].append(system_msg)
        await self.broadcast_message(system_msg)
    
    async def send_ai_response(self, message: Message):
        """Имитация AI-ответа"""
        await asyncio.sleep(1)  # Задержка для реалистичности
        
        ai_responses = [
            "🤖 Это интересный вопрос! Могу предложить обсудить это подробнее.",
            "🤖 На основе предыдущих обсуждений, рекомендую проверить документацию.",
            "🤖 Я LinkBot! Вижу у вас вопрос. Попробуйте задать его более конкретно.",
            "🤖 Пока я учусь, но скоро смогу давать более развёрнутые ответы!",
            "🤖 Запомнил ваш вопрос. Когда в чате появятся эксперты, они помогут."
        ]
        
        ai_msg = Message(
            id=str(uuid.uuid4()),
            type=MessageType.TEXT,
            content=secrets.choice(ai_responses),
            sender_id="ai_bot",
            channel_id=message.channel_id,
            timestamp=datetime.now().strftime("%H:%M"),
            metadata={"ai": True, "responding_to": message.id}
        )
        
        self.messages[message.channel_id].append(ai_msg)
        await self.broadcast_message(ai_msg)

# ========== ЗАПУСК СЕРВЕРА ==========
if __name__ == "__main__":
    server = DeeplinkServer()
    print("🚀 Deeplink Messenger Server запускается...")
    print("📱 Откройте в браузере: http://localhost:8000")
    print("📞 Оптимизировано для мобильных устройств")
    
    uvicorn.run(
        server.app,
        host="0.0.0.0",
        port=8000,
        reload=False
    )
