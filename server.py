from flask import Flask, render_template, request, jsonify, session, send_file
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS
import json
import os
import uuid
from datetime import datetime
import bcrypt
import logging

# Настройка логирования
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__, template_folder='.', static_folder='.')
CORS(app)
app.config['SECRET_KEY'] = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)

# In-memory хранилище (в реальном приложении используйте базу данных)
users_db = {}
chats_db = {}
messages_db = {}
typing_status = {}
online_users = {}

def get_user_by_id(user_id):
    return users_db.get(user_id)

def get_chat_by_id(chat_id):
    return chats_db.get(chat_id)

def get_messages_for_chat(chat_id, limit=100):
    return messages_db.get(chat_id, [])[-limit:]

def add_message_to_chat(chat_id, user_id, content):
    if chat_id not in messages_db:
        messages_db[chat_id] = []
    
    message = {
        'id': str(uuid.uuid4()),
        'chat_id': chat_id,
        'user_id': user_id,
        'content': content,
        'timestamp': datetime.now().isoformat(),
        'is_read': False
    }
    messages_db[chat_id].append(message)
    return message

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        if not username or not password:
            return jsonify({'success': False, 'error': 'Имя пользователя и пароль обязательны'})
        
        # Проверка уникальности username
        for user in users_db.values():
            if user['username'].lower() == username.lower():
                return jsonify({'success': False, 'error': 'Имя пользователя уже занято'})
        
        # Проверка что пароль не совпадает с username
        if password == username:
            return jsonify({'success': False, 'error': 'Пароль не может совпадать с именем пользователя'})
        
        user_id = str(uuid.uuid4())
        
        # Хеширование пароля
        password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
        
        # Создание пользователя
        user = {
            'id': user_id,
            'username': username,
            'password_hash': password_hash.decode('utf-8'),
            'nickname': username,
            'bio': '',
            'avatar': f'https://ui-avatars.com/api/?name={username}&background=0a0a0a&color=ffffff&bold=true',
            'status': 'online',
            'last_seen': datetime.now().isoformat(),
            'created_at': datetime.now().isoformat(),
            'is_online': True
        }
        
        users_db[user_id] = user
        
        # Создаем личный чат с самим собой (для системных сообщений)
        chat_id = str(uuid.uuid4())
        chat = {
            'id': chat_id,
            'type': 'self',
            'name': 'Избранное',
            'members': [user_id],
            'created_at': datetime.now().isoformat(),
            'last_message': None
        }
        chats_db[chat_id] = chat
        
        return jsonify({
            'success': True,
            'user': {
                'id': user_id,
                'username': user['username'],
                'nickname': user['nickname'],
                'avatar': user['avatar'],
                'bio': user['bio']
            }
        })
        
    except Exception as e:
        logging.error(f"Registration error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/login', methods=['POST'])
def login():
    try:
        data = request.get_json()
        username = data.get('username', '').strip()
        password = data.get('password', '').strip()
        
        # Поиск пользователя
        user = None
        for u in users_db.values():
            if u['username'].lower() == username.lower():
                user = u
                break
        
        if not user:
            return jsonify({'success': False, 'error': 'Пользователь не найден'})
        
        # Проверка пароля
        if not bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
            return jsonify({'success': False, 'error': 'Неверный пароль'})
        
        # Обновляем статус
        user['is_online'] = True
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
        
    except Exception as e:
        logging.error(f"Login error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/user/<user_id>')
def get_user(user_id):
    user = get_user_by_id(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    
    return jsonify({
        'id': user['id'],
        'username': user['username'],
        'nickname': user['nickname'],
        'avatar': user['avatar'],
        'bio': user['bio'],
        'status': user['status'],
        'is_online': user['is_online'],
        'last_seen': user['last_seen']
    })

@app.route('/api/user/update', methods=['POST'])
def update_user():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        updates = data.get('updates', {})
        
        user = get_user_by_id(user_id)
        if not user:
            return jsonify({'success': False, 'error': 'Пользователь не найден'})
        
        # Проверка уникальности username
        if 'username' in updates:
            new_username = updates['username'].strip()
            for u in users_db.values():
                if u['id'] != user_id and u['username'].lower() == new_username.lower():
                    return jsonify({'success': False, 'error': 'Имя пользователя уже занято'})
        
        # Обновляем поля
        allowed_fields = ['username', 'nickname', 'bio', 'avatar', 'status']
        for field in allowed_fields:
            if field in updates:
                user[field] = updates[field]
        
        return jsonify({'success': True, 'user': user})
        
    except Exception as e:
        logging.error(f"Update user error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/chats')
def get_chats():
    try:
        user_id = request.args.get('user_id')
        if not user_id:
            return jsonify({'error': 'user_id required'}), 400
        
        user_chats = []
        for chat in chats_db.values():
            if user_id in chat.get('members', []):
                chat_data = chat.copy()
                
                # Получаем последнее сообщение
                messages = get_messages_for_chat(chat['id'], limit=1)
                if messages:
                    last_msg = messages[-1]
                    user = get_user_by_id(last_msg['user_id'])
                    chat_data['last_message'] = {
                        'content': last_msg['content'],
                        'timestamp': last_msg['timestamp'],
                        'user': user['nickname'] if user else 'Unknown'
                    }
                else:
                    chat_data['last_message'] = None
                
                # Для групповых чатов получаем информацию об участниках
                if chat['type'] == 'group':
                    members_info = []
                    for member_id in chat['members']:
                        member = get_user_by_id(member_id)
                        if member:
                            members_info.append({
                                'id': member['id'],
                                'nickname': member['nickname'],
                                'avatar': member['avatar']
                            })
                    chat_data['members_info'] = members_info
                
                user_chats.append(chat_data)
        
        return jsonify(user_chats)
        
    except Exception as e:
        logging.error(f"Get chats error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/chat/<chat_id>/messages')
def get_chat_messages(chat_id):
    try:
        messages = get_messages_for_chat(chat_id, limit=100)
        
        # Добавляем информацию о пользователях
        enriched_messages = []
        for msg in messages:
            user = get_user_by_id(msg['user_id'])
            enriched_msg = msg.copy()
            enriched_msg['user'] = {
                'id': user['id'] if user else None,
                'nickname': user['nickname'] if user else 'Unknown',
                'avatar': user['avatar'] if user else None
            }
            enriched_messages.append(enriched_msg)
        
        return jsonify(enriched_messages)
        
    except Exception as e:
        logging.error(f"Get messages error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/search')
def search_users():
    try:
        query = request.args.get('q', '').strip().lower()
        if not query:
            return jsonify([])
        
        results = []
        for user in users_db.values():
            if (query in user['username'].lower() or 
                query in user['nickname'].lower()):
                results.append({
                    'id': user['id'],
                    'username': user['username'],
                    'nickname': user['nickname'],
                    'avatar': user['avatar'],
                    'is_online': user['is_online']
                })
        
        return jsonify(results[:20])  # Ограничиваем результаты
        
    except Exception as e:
        logging.error(f"Search error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/chat/create', methods=['POST'])
def create_chat():
    try:
        data = request.get_json()
        user_id = data.get('user_id')
        target_user_id = data.get('target_user_id')
        is_group = data.get('is_group', False)
        group_name = data.get('group_name', '')
        
        if not user_id:
            return jsonify({'success': False, 'error': 'user_id required'})
        
        if not is_group and not target_user_id:
            return jsonify({'success': False, 'error': 'target_user_id required for private chat'})
        
        # Проверяем существование пользователей
        if not get_user_by_id(user_id):
            return jsonify({'success': False, 'error': 'User not found'})
        
        if not is_group and not get_user_by_id(target_user_id):
            return jsonify({'success': False, 'error': 'Target user not found'})
        
        # Для приватных чатов проверяем существующий чат
        if not is_group:
            for chat in chats_db.values():
                if (chat['type'] == 'private' and 
                    user_id in chat['members'] and 
                    target_user_id in chat['members']):
                    return jsonify({'success': True, 'chat': chat})
        
        # Создаем новый чат
        chat_id = str(uuid.uuid4())
        
        if is_group:
            chat = {
                'id': chat_id,
                'type': 'group',
                'name': group_name or f'Группа {datetime.now().strftime("%H:%M")}',
                'members': [user_id],
                'created_at': datetime.now().isoformat(),
                'last_message': None
            }
        else:
            user1 = get_user_by_id(user_id)
            user2 = get_user_by_id(target_user_id)
            chat = {
                'id': chat_id,
                'type': 'private',
                'name': f'{user1["nickname"]} & {user2["nickname"]}',
                'members': [user_id, target_user_id],
                'created_at': datetime.now().isoformat(),
                'last_message': None
            }
        
        chats_db[chat_id] = chat
        
        # Создаем приветственное сообщение
        if is_group:
            welcome_msg = f'Группа "{chat["name"]}" создана'
        else:
            welcome_msg = 'Чат создан'
        
        add_message_to_chat(chat_id, 'system', welcome_msg)
        
        return jsonify({'success': True, 'chat': chat})
        
    except Exception as e:
        logging.error(f"Create chat error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)})

# WebSocket события
@socketio.on('connect')
def handle_connect():
    logging.info(f'Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    logging.info(f'Client disconnected: {request.sid}')

@socketio.on('user_online')
def handle_user_online(data):
    user_id = data.get('user_id')
    if user_id:
        online_users[user_id] = request.sid
        user = get_user_by_id(user_id)
        if user:
            user['is_online'] = True
            user['last_seen'] = datetime.now().isoformat()
        
        # Уведомляем всех о новом статусе
        emit('user_status_changed', {
            'user_id': user_id,
            'is_online': True,
            'last_seen': datetime.now().isoformat()
        }, broadcast=True)

@socketio.on('user_offline')
def handle_user_offline(data):
    user_id = data.get('user_id')
    if user_id and user_id in online_users:
        del online_users[user_id]
        user = get_user_by_id(user_id)
        if user:
            user['is_online'] = False
            user['last_seen'] = datetime.now().isoformat()
        
        emit('user_status_changed', {
            'user_id': user_id,
            'is_online': False,
            'last_seen': datetime.now().isoformat()
        }, broadcast=True)

@socketio.on('join_chat')
def handle_join_chat(data):
    chat_id = data.get('chat_id')
    user_id = data.get('user_id')
    
    if chat_id and user_id:
        join_room(chat_id)
        logging.info(f'User {user_id} joined chat {chat_id}')

@socketio.on('leave_chat')
def handle_leave_chat(data):
    chat_id = data.get('chat_id')
    user_id = data.get('user_id')
    
    if chat_id and user_id:
        leave_room(chat_id)
        logging.info(f'User {user_id} left chat {chat_id}')

@socketio.on('send_message')
def handle_send_message(data):
    try:
        chat_id = data.get('chat_id')
        user_id = data.get('user_id')
        content = data.get('content', '').strip()
        
        if not all([chat_id, user_id, content]):
            return
        
        # Добавляем сообщение
        message = add_message_to_chat(chat_id, user_id, content)
        
        # Получаем информацию о пользователе
        user = get_user_by_id(user_id)
        
        # Подготавливаем данные для отправки
        message_data = {
            'id': message['id'],
            'chat_id': chat_id,
            'user_id': user_id,
            'content': content,
            'timestamp': message['timestamp'],
            'user': {
                'id': user['id'] if user else None,
                'nickname': user['nickname'] if user else 'Unknown',
                'avatar': user['avatar'] if user else None
            }
        }
        
        # Отправляем всем в комнате чата
        emit('new_message', message_data, room=chat_id, broadcast=True)
        
        # Обновляем информацию о последнем сообщении в чате
        chat = get_chat_by_id(chat_id)
        if chat:
            chat['last_message'] = {
                'content': content,
                'timestamp': message['timestamp'],
                'user_id': user_id
            }
        
        logging.info(f'Message sent to chat {chat_id} by user {user_id}')
        
    except Exception as e:
        logging.error(f"Send message error: {str(e)}")

@socketio.on('typing')
def handle_typing(data):
    chat_id = data.get('chat_id')
    user_id = data.get('user_id')
    is_typing = data.get('is_typing', False)
    
    if not all([chat_id, user_id]):
        return
    
    user = get_user_by_id(user_id)
    if not user:
        return
    
    typing_data = {
        'chat_id': chat_id,
        'user_id': user_id,
        'user_nickname': user['nickname'],
        'is_typing': is_typing
    }
    
    # Отправляем всем в комнате чата, кроме отправителя
    emit('user_typing', typing_data, room=chat_id, include_self=False, broadcast=True)

if __name__ == '__main__':
    # Добавляем тестовых пользователей
    if not users_db:
        test_users = [
            {'username': 'alice', 'nickname': 'Alice', 'password': 'password123'},
            {'username': 'bob', 'nickname': 'Bob', 'password': 'password123'},
            {'username': 'charlie', 'nickname': 'Charlie', 'password': 'password123'}
        ]
        
        for user_data in test_users:
            user_id = str(uuid.uuid4())
            password_hash = bcrypt.hashpw(user_data['password'].encode('utf-8'), bcrypt.gensalt())
            
            user = {
                'id': user_id,
                'username': user_data['username'],
                'password_hash': password_hash.decode('utf-8'),
                'nickname': user_data['nickname'],
                'bio': f'Привет, я {user_data["nickname"]}!',
                'avatar': f'https://ui-avatars.com/api/?name={user_data["username"]}&background=0a0a0a&color=ffffff&bold=true',
                'status': 'online',
                'last_seen': datetime.now().isoformat(),
                'created_at': datetime.now().isoformat(),
                'is_online': True
            }
            users_db[user_id] = user
        
        # Создаем тестовый чат
        user_ids = list(users_db.keys())
        if len(user_ids) >= 2:
            chat_id = str(uuid.uuid4())
            chat = {
                'id': chat_id,
                'type': 'private',
                'name': f'{users_db[user_ids[0]]["nickname"]} & {users_db[user_ids[1]]["nickname"]}',
                'members': [user_ids[0], user_ids[1]],
                'created_at': datetime.now().isoformat(),
                'last_message': None
            }
            chats_db[chat_id] = chat
            
            # Добавляем тестовые сообщения
            add_message_to_chat(chat_id, user_ids[0], 'Привет! Как дела?')
            add_message_to_chat(chat_id, user_ids[1], 'Привет! Все отлично, спасибо!')
            add_message_to_chat(chat_id, user_ids[0], 'Рад это слышать! 😊')
    
    socketio.run(app, 
                 host='0.0.0.0', 
                 port=10000, 
                 allow_unsafe_werkzeug=True,
                 debug=True)
