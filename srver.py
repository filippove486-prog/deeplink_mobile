from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
import json
import os
import uuid
from datetime import datetime
from collections import defaultdict
import logging

logging.basicConfig(level=logging.INFO)

app = Flask(__name__, template_folder='.', static_folder='.')
app.config['SECRET_KEY'] = 'deeplink-neon-secret-2024'
socketio = SocketIO(app, cors_allowed_origins="*")

# База данных в памяти
users = {}
chats = {}
messages = defaultdict(list)
user_chats = defaultdict(set)
online_users = {}
user_settings = defaultdict(dict)
deleted_messages = set()  # Для удаленных сообщений
message_reactions = defaultdict(dict)  # Реакции на сообщения
user_presence = {}  # Онлайн статус
typing_status = {}  # Статус набора

def generate_avatar(username):
    return f"https://ui-avatars.com/api/?name={username}&background=0a0a0a&color=ffffff&bold=true&size=128"

@app.route('/')
def index():
    return render_template('index.html')

# API
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json()
    username = data.get('username', '').strip().lower()
    password = data.get('password', '').strip()
    nickname = data.get('nickname', '').strip() or username
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Заполните все поля'})
    
    if username in users:
        return jsonify({'success': False, 'error': 'Имя пользователя уже занято'})
    
    if password == username:
        return jsonify({'success': False, 'error': 'Пароль не может совпадать с логином'})
    
    user_id = str(uuid.uuid4())
    users[username] = {
        'id': user_id,
        'username': username,
        'password': password,
        'nickname': nickname,
        'avatar': generate_avatar(username),
        'bio': f'Привет, я {nickname}!',
        'status': 'online',
        'last_seen': datetime.now().isoformat(),
        'created_at': datetime.now().isoformat(),
        'privacy': 'public',
        'theme': 'dark'
    }
    
    # Создаем настройки по умолчанию
    user_settings[username] = {
        'notifications': True,
        'sound': True,
        'vibration': True,
        'show_online': True,
        'read_receipts': True,
        'message_preview': True,
        'auto_download': True,
        'save_to_gallery': False
    }
    
    return jsonify({
        'success': True,
        'user': {
            'username': username,
            'nickname': nickname,
            'avatar': generate_avatar(username),
            'bio': ''
        }
    })

@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json()
    username = data.get('username', '').strip().lower()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Заполните все поля'})
    
    user = users.get(username)
    if not user:
        return jsonify({'success': False, 'error': 'Пользователь не найден'})
    
    if user['password'] != password:
        return jsonify({'success': False, 'error': 'Неверный пароль'})
    
    user['status'] = 'online'
    user['last_seen'] = datetime.now().isoformat()
    
    return jsonify({
        'success': True,
        'user': {
            'username': user['username'],
            'nickname': user['nickname'],
            'avatar': user['avatar'],
            'bio': user['bio']
        }
    })

@app.route('/api/search', methods=['GET'])
def api_search():
    query = request.args.get('q', '').strip().lower()
    current_user = request.args.get('current_user', '')
    
    if not query:
        return jsonify([])
    
    results = []
    for username, user in users.items():
        if username == current_user:
            continue
        
        if (query in username.lower() or 
            query in user.get('nickname', '').lower()):
            results.append({
                'username': user['username'],
                'nickname': user['nickname'],
                'avatar': user['avatar'],
                'status': user['status'],
                'last_seen': user['last_seen'],
                'bio': user['bio'][:100] + '...' if len(user['bio']) > 100 else user['bio']
            })
    
    return jsonify(results[:50])

@app.route('/api/chats', methods=['GET'])
def api_chats():
    username = request.args.get('username')
    if not username:
        return jsonify([])
    
    user_chats_list = []
    for chat_id in user_chats.get(username, set()):
        chat = chats.get(chat_id)
        if chat:
            chat_data = chat.copy()
            
            # Для приватных чатов получаем информацию о собеседнике
            if chat['type'] == 'private':
                other_user = [u for u in chat['members'] if u != username][0]
                other_data = users.get(other_user, {})
                chat_data['display_name'] = other_data.get('nickname', other_user)
                chat_data['avatar'] = other_data.get('avatar', generate_avatar(other_user))
                chat_data['status'] = other_data.get('status', 'offline')
            
            # Получаем последнее сообщение
            chat_messages = messages.get(chat_id, [])
            last_msg = None
            for msg in reversed(chat_messages):
                if msg['id'] not in deleted_messages:
                    last_msg = msg
                    break
            
            if last_msg:
                chat_data['last_message'] = {
                    'text': last_msg['content'],
                    'time': last_msg['timestamp'],
                    'sender': last_msg['sender']
                }
                # Считаем непрочитанные
                unread = sum(1 for msg in chat_messages 
                           if msg['sender'] != username and not msg.get('read', False) and msg['id'] not in deleted_messages)
                chat_data['unread'] = unread
            
            user_chats_list.append(chat_data)
    
    # Сортируем по времени последнего сообщения
    user_chats_list.sort(key=lambda x: x.get('last_message', {}).get('time', ''), reverse=True)
    return jsonify(user_chats_list)

@app.route('/api/chat/<chat_id>/messages', methods=['GET'])
def api_chat_messages(chat_id):
    username = request.args.get('username')
    
    if chat_id not in messages:
        return jsonify([])
    
    # Возвращаем только неудаленные сообщения
    chat_messages = [msg for msg in messages[chat_id] if msg['id'] not in deleted_messages]
    
    # Помечаем сообщения как прочитанные
    for msg in chat_messages:
        if msg['sender'] != username:
            msg['read'] = True
    
    # Добавляем реакции к сообщениям
    for msg in chat_messages:
        msg_id = msg['id']
        if msg_id in message_reactions:
            msg['reactions'] = message_reactions[msg_id]
    
    return jsonify(chat_messages)

@app.route('/api/chat/create', methods=['POST'])
def api_chat_create():
    data = request.get_json()
    user1 = data.get('user1')
    user2 = data.get('user2')
    
    if not user1 or not user2:
        return jsonify({'success': False, 'error': 'Не указаны пользователи'})
    
    # Проверяем существующий чат
    for chat_id, chat in chats.items():
        if (chat['type'] == 'private' and 
            user1 in chat['members'] and 
            user2 in chat['members']):
            return jsonify({'success': True, 'chat_id': chat_id, 'exists': True})
    
    # Создаем новый чат
    chat_id = str(uuid.uuid4())
    
    user1_data = users.get(user1, {})
    user2_data = users.get(user2, {})
    
    chat_name = f"{user1_data.get('nickname', user1)} и {user2_data.get('nickname', user2)}"
    
    chats[chat_id] = {
        'id': chat_id,
        'type': 'private',
        'name': chat_name,
        'members': [user1, user2],
        'created_at': datetime.now().isoformat(),
        'last_message': None,
        'unread': 0
    }
    
    user_chats[user1].add(chat_id)
    user_chats[user2].add(chat_id)
    
    # Добавляем приветственное сообщение
    welcome_msg = {
        'id': str(uuid.uuid4()),
        'chat_id': chat_id,
        'sender': 'system',
        'content': 'Чат создан. Начните общение!',
        'timestamp': datetime.now().isoformat(),
        'read': True
    }
    messages[chat_id].append(welcome_msg)
    
    return jsonify({'success': True, 'chat_id': chat_id, 'exists': False})

@app.route('/api/user/update', methods=['POST'])
def api_user_update():
    data = request.get_json()
    username = data.get('username')
    updates = data.get('updates', {})
    
    if not username or username not in users:
        return jsonify({'success': False, 'error': 'Пользователь не найден'})
    
    user = users[username]
    
    if 'nickname' in updates:
        user['nickname'] = updates['nickname']
    
    if 'bio' in updates:
        user['bio'] = updates['bio']
    
    if 'avatar' in updates:
        user['avatar'] = updates['avatar']
    
    if 'privacy' in updates:
        user['privacy'] = updates['privacy']
    
    if 'theme' in updates:
        user['theme'] = updates['theme']
    
    return jsonify({'success': True, 'user': user})

@app.route('/api/settings/update', methods=['POST'])
def api_settings_update():
    data = request.get_json()
    username = data.get('username')
    settings = data.get('settings', {})
    
    if not username or username not in user_settings:
        return jsonify({'success': False, 'error': 'Пользователь не найден'})
    
    user_settings[username].update(settings)
    return jsonify({'success': True, 'settings': user_settings[username]})

@app.route('/api/user/<username>', methods=['GET'])
def api_get_user(username):
    user = users.get(username)
    if not user:
        return jsonify({'error': 'Пользователь не найден'}), 404
    
    return jsonify({
        'username': user['username'],
        'nickname': user['nickname'],
        'avatar': user['avatar'],
        'bio': user['bio'],
        'status': user['status'],
        'last_seen': user['last_seen'],
        'created_at': user['created_at']
    })

@app.route('/api/message/delete', methods=['POST'])
def api_message_delete():
    data = request.get_json()
    message_id = data.get('message_id')
    username = data.get('username')
    
    if not message_id or not username:
        return jsonify({'success': False, 'error': 'Не указаны данные'})
    
    # Ищем сообщение во всех чатах
    for chat_id, chat_messages in messages.items():
        for msg in chat_messages:
            if msg['id'] == message_id:
                # Проверяем, что пользователь может удалить сообщение
                if msg['sender'] == username or username in chats[chat_id]['members']:
                    deleted_messages.add(message_id)
                    
                    # Уведомляем всех в чате
                    socketio.emit('message_deleted', {
                        'message_id': message_id,
                        'chat_id': chat_id,
                        'deleted_by': username
                    }, room=chat_id)
                    
                    return jsonify({'success': True})
    
    return jsonify({'success': False, 'error': 'Сообщение не найдено'})

@app.route('/api/message/react', methods=['POST'])
def api_message_react():
    data = request.get_json()
    message_id = data.get('message_id')
    username = data.get('username')
    reaction = data.get('reaction')
    
    if not all([message_id, username, reaction]):
        return jsonify({'success': False, 'error': 'Не указаны данные'})
    
    if message_id not in message_reactions:
        message_reactions[message_id] = {}
    
    if username in message_reactions[message_id]:
        # Удаляем реакцию, если она уже есть
        del message_reactions[message_id][username]
        if not message_reactions[message_id]:
            del message_reactions[message_id]
    else:
        # Добавляем реакцию
        message_reactions[message_id][username] = reaction
    
    # Находим chat_id для сообщения
    chat_id = None
    for cid, chat_messages in messages.items():
        for msg in chat_messages:
            if msg['id'] == message_id:
                chat_id = cid
                break
        if chat_id:
            break
    
    if chat_id:
        # Отправляем обновление всем в чате
        socketio.emit('message_reaction', {
            'message_id': message_id,
            'username': username,
            'reaction': reaction,
            'chat_id': chat_id,
            'reactions': message_reactions.get(message_id, {})
        }, room=chat_id)
    
    return jsonify({'success': True, 'reactions': message_reactions.get(message_id, {})})

@app.route('/api/chat/<chat_id>/clear', methods=['POST'])
def api_chat_clear():
    data = request.get_json()
    chat_id = data.get('chat_id')
    username = data.get('username')
    
    if not chat_id or not username:
        return jsonify({'success': False, 'error': 'Не указаны данные'})
    
    if chat_id not in chats or username not in chats[chat_id]['members']:
        return jsonify({'success': False, 'error': 'Доступ запрещен'})
    
    # Помечаем все сообщения как удаленные для этого пользователя
    for msg in messages.get(chat_id, []):
        if msg['sender'] != username:  # Не удаляем чужие сообщения полностью
            deleted_messages.add(msg['id'])
    
    return jsonify({'success': True})

# WebSocket
@socketio.on('connect')
def handle_connect():
    logging.info(f'Client connected: {request.sid}')

@socketio.on('disconnect')
def handle_disconnect():
    for username, socket_id in online_users.items():
        if socket_id == request.sid:
            del online_users[username]
            if username in users:
                users[username]['status'] = 'offline'
                users[username]['last_seen'] = datetime.now().isoformat()
            emit('user_offline', {'username': username}, broadcast=True)
            break

@socketio.on('user_online')
def handle_user_online(data):
    username = data.get('username')
    if username:
        online_users[username] = request.sid
        if username in users:
            users[username]['status'] = 'online'
            users[username]['last_seen'] = datetime.now().isoformat()
        emit('user_online', {'username': username}, broadcast=True)

@socketio.on('join_chat')
def handle_join_chat(data):
    chat_id = data.get('chat_id')
    if chat_id:
        join_room(chat_id)

@socketio.on('leave_chat')
def handle_leave_chat(data):
    chat_id = data.get('chat_id')
    if chat_id:
        leave_room(chat_id)

@socketio.on('send_message')
def handle_send_message(data):
    chat_id = data.get('chat_id')
    sender = data.get('sender')
    content = data.get('content', '').strip()
    
    if not all([chat_id, sender, content]):
        return
    
    # Создаем сообщение
    message = {
        'id': str(uuid.uuid4()),
        'chat_id': chat_id,
        'sender': sender,
        'content': content,
        'timestamp': datetime.now().isoformat(),
        'read': False,
        'edited': False
    }
    
    # Сохраняем сообщение
    messages[chat_id].append(message)
    
    # Обновляем последнее сообщение в чате
    if chat_id in chats:
        chats[chat_id]['last_message'] = {
            'text': content,
            'time': message['timestamp'],
            'sender': sender
        }
    
    # Отправляем всем в комнате чата
    emit('new_message', message, room=chat_id, broadcast=True)

@socketio.on('typing')
def handle_typing(data):
    chat_id = data.get('chat_id')
    username = data.get('username')
    is_typing = data.get('is_typing')
    
    if chat_id and username:
        typing_status[(chat_id, username)] = datetime.now().isoformat() if is_typing else None
        
        emit('user_typing', {
            'chat_id': chat_id,
            'username': username,
            'is_typing': is_typing
        }, room=chat_id, include_self=False)

@socketio.on('read_message')
def handle_read_message(data):
    chat_id = data.get('chat_id')
    username = data.get('username')
    message_id = data.get('message_id')
    
    if chat_id and username and message_id:
        # Помечаем сообщение как прочитанное
        for msg in messages.get(chat_id, []):
            if msg['id'] == message_id and msg['sender'] != username:
                msg['read'] = True
                break

@socketio.on('edit_message')
def handle_edit_message(data):
    message_id = data.get('message_id')
    chat_id = data.get('chat_id')
    username = data.get('username')
    new_content = data.get('content', '').strip()
    
    if not all([message_id, chat_id, username, new_content]):
        return
    
    # Ищем и редактируем сообщение
    for msg in messages.get(chat_id, []):
        if msg['id'] == message_id and msg['sender'] == username:
            msg['content'] = new_content
            msg['edited'] = True
            msg['edited_at'] = datetime.now().isoformat()
            
            emit('message_edited', {
                'message_id': message_id,
                'chat_id': chat_id,
                'content': new_content,
                'edited_at': msg['edited_at']
            }, room=chat_id, broadcast=True)
            break

if __name__ == '__main__':
    # Создаем тестовых пользователей
    test_users = [
        {'username': 'alice', 'nickname': 'Алиса', 'bio': 'Люблю программирование и котиков!'},
        {'username': 'bob', 'nickname': 'Боб', 'bio': 'Фотограф, путешественник'},
        {'username': 'charlie', 'nickname': 'Чарли', 'bio': 'Музыкант и геймдев'},
        {'username': 'diana', 'nickname': 'Диана', 'bio': 'Дизайнер интерфейсов'},
        {'username': 'evan', 'nickname': 'Эван', 'bio': 'Стартапер и инвестор'}
    ]
    
    for user_data in test_users:
        username = user_data['username']
        if username not in users:
            user_id = str(uuid.uuid4())
            users[username] = {
                'id': user_id,
                'username': username,
                'password': 'password123',
                'nickname': user_data['nickname'],
                'avatar': generate_avatar(username),
                'bio': user_data['bio'],
                'status': 'online',
                'last_seen': datetime.now().isoformat(),
                'created_at': datetime.now().isoformat(),
                'privacy': 'public',
                'theme': 'dark'
            }
            user_settings[username] = {
                'notifications': True,
                'sound': True,
                'vibration': True,
                'show_online': True,
                'read_receipts': True,
                'message_preview': True,
                'auto_download': True,
                'save_to_gallery': False
            }
    
    # Создаем тестовый чат
    if True:
        chat_id = str(uuid.uuid4())
        chats[chat_id] = {
            'id': chat_id,
            'type': 'private',
            'name': 'Алиса и Боб',
            'members': ['alice', 'bob'],
            'created_at': datetime.now().isoformat(),
            'last_message': None,
            'unread': 0
        }
        user_chats['alice'].add(chat_id)
        user_chats['bob'].add(chat_id)
        
        # Тестовые сообщения
        test_msgs = [
            {'sender': 'alice', 'content': 'Привет Боб! Как дела?'},
            {'sender': 'bob', 'content': 'Привет Алиса! Всё отлично, только что вернулся из поездки'},
            {'sender': 'alice', 'content': 'Круто! Куда ездил?'},
            {'sender': 'bob', 'content': 'Был в горах, снимал природу 📸'},
            {'sender': 'alice', 'content': 'Обязательно покажи фото!'},
            {'sender': 'bob', 'content': 'Конечно, вечером скину лучшие кадры 😊'},
        ]
        
        for msg_data in test_msgs:
            message = {
                'id': str(uuid.uuid4()),
                'chat_id': chat_id,
                'sender': msg_data['sender'],
                'content': msg_data['content'],
                'timestamp': datetime.now().isoformat(),
                'read': True,
                'edited': False
            }
            messages[chat_id].append(message)
        
        # Обновляем последнее сообщение
        chats[chat_id]['last_message'] = {
            'text': test_msgs[-1]['content'],
            'time': datetime.now().isoformat(),
            'sender': test_msgs[-1]['sender']
        }
    
    socketio.run(app, host='0.0.0.0', port=10000, allow_unsafe_werkzeug=True, debug=True)
