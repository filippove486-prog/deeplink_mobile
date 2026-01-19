from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room
import json
import os
import uuid
from datetime import datetime
from typing import Dict, List
import logging

logging.basicConfig(level=logging.INFO)

app = Flask(__name__, template_folder='.', static_folder='.')
app.config['SECRET_KEY'] = 'deeplink-secret-key-2024'
socketio = SocketIO(app, cors_allowed_origins="*")

# База данных в памяти
users_db = {}
chats_db = {}
messages_db = {}
online_users = {}

def generate_avatar(name):
    return f"https://ui-avatars.com/api/?name={name}&background=0a0a0a&color=ffffff&bold=true"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Заполните все поля'})
    
    if username in users_db:
        return jsonify({'success': False, 'error': 'Имя пользователя уже занято'})
    
    if password == username:
        return jsonify({'success': False, 'error': 'Пароль не может совпадать с логином'})
    
    user_id = str(uuid.uuid4())
    users_db[username] = {
        'id': user_id,
        'username': username,
        'password': password,  # В реальном приложении хешируйте пароль!
        'nickname': username,
        'avatar': generate_avatar(username),
        'bio': f'Привет, я {username}!',
        'status': 'online',
        'created_at': datetime.now().isoformat(),
        'last_seen': datetime.now().isoformat()
    }
    
    # Создаем чат с самим собой для избранного
    chat_id = str(uuid.uuid4())
    chats_db[chat_id] = {
        'id': chat_id,
        'type': 'self',
        'name': 'Избранное',
        'members': [username],
        'created_at': datetime.now().isoformat(),
        'last_message': None,
        'unread': 0
    }
    
    return jsonify({
        'success': True,
        'user': {
            'id': user_id,
            'username': username,
            'nickname': username,
            'avatar': generate_avatar(username),
            'bio': ''
        }
    })

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Заполните все поля'})
    
    user = users_db.get(username)
    if not user:
        return jsonify({'success': False, 'error': 'Пользователь не найден'})
    
    if user['password'] != password:  # В реальном приложении проверяйте хеш!
        return jsonify({'success': False, 'error': 'Неверный пароль'})
    
    user['status'] = 'online'
    user['last_seen'] = datetime.now().isoformat()
    
    return jsonify({
        'success': True,
        'user': {
            'id': user['id'],
            'username': user['username'],
            'nickname': user['nickname'],
            'avatar': user['avatar'],
            'bio': user['bio']
        }
    })

@app.route('/api/search', methods=['GET'])
def search_users():
    query = request.args.get('q', '').strip().lower()
    current_user = request.args.get('current_user', '')
    
    if not query:
        return jsonify([])
    
    results = []
    for username, user in users_db.items():
        if username == current_user:
            continue
            
        if (query in username.lower() or 
            query in user['nickname'].lower()):
            results.append({
                'id': user['id'],
                'username': user['username'],
                'nickname': user['nickname'],
                'avatar': user['avatar'],
                'status': user['status'],
                'last_seen': user['last_seen']
            })
    
    return jsonify(results[:20])

@app.route('/api/chats', methods=['GET'])
def get_chats():
    username = request.args.get('username')
    if not username:
        return jsonify([])
    
    user_chats = []
    for chat_id, chat in chats_db.items():
        if username in chat['members']:
            # Получаем последнее сообщение
            chat_messages = messages_db.get(chat_id, [])
            last_message = chat_messages[-1] if chat_messages else None
            
            # Получаем информацию о другом пользователе для приватных чатов
            chat_info = chat.copy()
            
            if chat['type'] == 'private':
                other_member = [m for m in chat['members'] if m != username][0]
                other_user = users_db.get(other_member)
                if other_user:
                    chat_info['display_name'] = other_user['nickname']
                    chat_info['avatar'] = other_user['avatar']
                    chat_info['status'] = other_user['status']
            
            if last_message:
                chat_info['last_message'] = {
                    'text': last_message['content'][:50] + ('...' if len(last_message['content']) > 50 else ''),
                    'time': last_message['timestamp'],
                    'sender': last_message['sender']
                }
            
            user_chats.append(chat_info)
    
    # Сортируем по времени последнего сообщения
    user_chats.sort(key=lambda x: x.get('last_message', {}).get('time', ''), reverse=True)
    
    return jsonify(user_chats)

@app.route('/api/chat/<chat_id>/messages', methods=['GET'])
def get_messages(chat_id):
    username = request.args.get('username')
    
    if chat_id not in messages_db:
        messages_db[chat_id] = []
    
    # Помечаем сообщения как прочитанные
    for msg in messages_db[chat_id]:
        if msg['sender'] != username:
            msg['read'] = True
    
    return jsonify(messages_db[chat_id])

@app.route('/api/chat/create', methods=['POST'])
def create_chat():
    data = request.get_json()
    user1 = data.get('user1')
    user2 = data.get('user2')
    
    if not user1 or not user2:
        return jsonify({'success': False, 'error': 'Не указаны пользователи'})
    
    # Проверяем существующий чат
    for chat_id, chat in chats_db.items():
        if (chat['type'] == 'private' and 
            user1 in chat['members'] and 
            user2 in chat['members']):
            return jsonify({'success': True, 'chat_id': chat_id})
    
    # Создаем новый чат
    chat_id = str(uuid.uuid4())
    
    user1_info = users_db.get(user1)
    user2_info = users_db.get(user2)
    
    chat_name = f"{user1_info['nickname']} и {user2_info['nickname']}"
    
    chats_db[chat_id] = {
        'id': chat_id,
        'type': 'private',
        'name': chat_name,
        'members': [user1, user2],
        'created_at': datetime.now().isoformat(),
        'last_message': None,
        'unread': 0,
        'display_name': user2_info['nickname'],
        'avatar': user2_info['avatar'],
        'status': user2_info['status']
    }
    
    # Добавляем приветственное сообщение
    welcome_msg = {
        'id': str(uuid.uuid4()),
        'chat_id': chat_id,
        'sender': 'system',
        'content': 'Чат создан. Начните общение!',
        'timestamp': datetime.now().isoformat(),
        'read': True
    }
    
    if chat_id not in messages_db:
        messages_db[chat_id] = []
    messages_db[chat_id].append(welcome_msg)
    
    return jsonify({'success': True, 'chat_id': chat_id})

@app.route('/api/user/update', methods=['POST'])
def update_user():
    data = request.get_json()
    username = data.get('username')
    updates = data.get('updates', {})
    
    if not username or username not in users_db:
        return jsonify({'success': False, 'error': 'Пользователь не найден'})
    
    user = users_db[username]
    
    # Обновляем поля
    if 'nickname' in updates:
        user['nickname'] = updates['nickname']
    
    if 'bio' in updates:
        user['bio'] = updates['bio']
    
    if 'avatar' in updates and updates['avatar']:
        user['avatar'] = updates['avatar']
    
    return jsonify({'success': True, 'user': user})

# WebSocket события
@socketio.on('connect')
def handle_connect():
    logging.info(f'Клиент подключился: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    logging.info(f'Клиент отключился: {request.sid}')

@socketio.on('join')
def handle_join(data):
    username = data.get('username')
    if username:
        join_room(username)
        online_users[username] = request.sid
        
        # Обновляем статус пользователя
        if username in users_db:
            users_db[username]['status'] = 'online'
            users_db[username]['last_seen'] = datetime.now().isoformat()
        
        emit('user_online', {'username': username}, broadcast=True)

@socketio.on('leave')
def handle_leave(data):
    username = data.get('username')
    if username and username in online_users:
        leave_room(username)
        del online_users[username]
        
        if username in users_db:
            users_db[username]['status'] = 'offline'
            users_db[username]['last_seen'] = datetime.now().isoformat()
        
        emit('user_offline', {'username': username}, broadcast=True)

@socketio.on('join_chat')
def handle_join_chat(data):
    chat_id = data.get('chat_id')
    if chat_id:
        join_room(f'chat_{chat_id}')

@socketio.on('send_message')
def handle_send_message(data):
    chat_id = data.get('chat_id')
    sender = data.get('sender')
    content = data.get('content')
    
    if not all([chat_id, sender, content]):
        return
    
    # Создаем сообщение
    message = {
        'id': str(uuid.uuid4()),
        'chat_id': chat_id,
        'sender': sender,
        'content': content,
        'timestamp': datetime.now().isoformat(),
        'read': False
    }
    
    # Сохраняем сообщение
    if chat_id not in messages_db:
        messages_db[chat_id] = []
    messages_db[chat_id].append(message)
    
    # Обновляем последнее сообщение в чате
    if chat_id in chats_db:
        chats_db[chat_id]['last_message'] = {
            'text': content[:50] + ('...' if len(content) > 50 else ''),
            'time': message['timestamp'],
            'sender': sender
        }
        chats_db[chat_id]['unread'] += 1
    
    # Отправляем всем участникам чата
    emit('new_message', message, room=f'chat_{chat_id}', broadcast=True)
    
    # Уведомляем участников (кроме отправителя)
    chat = chats_db.get(chat_id)
    if chat:
        for member in chat['members']:
            if member != sender and member in online_users:
                emit('message_notification', {
                    'chat_id': chat_id,
                    'sender': sender,
                    'content': content[:30] + ('...' if len(content) > 30 else '')
                }, room=member)

@socketio.on('typing')
def handle_typing(data):
    chat_id = data.get('chat_id')
    username = data.get('username')
    is_typing = data.get('is_typing')
    
    if chat_id and username:
        # Отправляем всем в чате, кроме отправителя
        emit('user_typing', {
            'chat_id': chat_id,
            'username': username,
            'is_typing': is_typing
        }, room=f'chat_{chat_id}', include_self=False)

if __name__ == '__main__':
    # Создаем тестовых пользователей
    test_users = ['alice', 'bob', 'charlie', 'diana', 'evan']
    
    for username in test_users:
        if username not in users_db:
            user_id = str(uuid.uuid4())
            users_db[username] = {
                'id': user_id,
                'username': username,
                'password': 'password123',
                'nickname': username.capitalize(),
                'avatar': generate_avatar(username),
                'bio': f'Привет, я {username.capitalize()}!',
                'status': 'online',
                'created_at': datetime.now().isoformat(),
                'last_seen': datetime.now().isoformat()
            }
            
            # Создаем личный чат
            chat_id = str(uuid.uuid4())
            chats_db[chat_id] = {
                'id': chat_id,
                'type': 'self',
                'name': 'Избранное',
                'members': [username],
                'created_at': datetime.now().isoformat(),
                'last_message': None,
                'unread': 0
            }
    
    # Создаем тестовый чат между Alice и Bob
    chat_id = str(uuid.uuid4())
    chats_db[chat_id] = {
        'id': chat_id,
        'type': 'private',
        'name': 'Alice и Bob',
        'members': ['alice', 'bob'],
        'created_at': datetime.now().isoformat(),
        'last_message': None,
        'unread': 0,
        'display_name': 'Bob',
        'avatar': generate_avatar('bob'),
        'status': 'online'
    }
    
    # Добавляем тестовые сообщения
    test_messages = [
        {'sender': 'alice', 'content': 'Привет Bob! Как дела?'},
        {'sender': 'bob', 'content': 'Привет Alice! Все отлично, спасибо!'},
        {'sender': 'alice', 'content': 'Рад это слышать! 😊'},
        {'sender': 'bob', 'content': 'Что нового?'}
    ]
    
    messages_db[chat_id] = []
    for msg_data in test_messages:
        message = {
            'id': str(uuid.uuid4()),
            'chat_id': chat_id,
            'sender': msg_data['sender'],
            'content': msg_data['content'],
            'timestamp': datetime.now().isoformat(),
            'read': True
        }
        messages_db[chat_id].append(message)
    
    # Обновляем последнее сообщение
    chats_db[chat_id]['last_message'] = {
        'text': test_messages[-1]['content'],
        'time': datetime.now().isoformat(),
        'sender': test_messages[-1]['sender']
    }
    
    socketio.run(app, host='0.0.0.0', port=10000, allow_unsafe_werkzeug=True, debug=True)
