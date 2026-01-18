import os
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, template_folder='.', static_folder='.')
app.config['SECRET_KEY'] = 'deeplink-neon-secret-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///deeplink.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 365  # 1 год

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
db = SQLAlchemy(app)

# Модели
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.Text, default='https://api.dicebear.com/7.x/avataaars/svg?seed={username}&background=0a0a0a&color=00ffff')
    bio = db.Column(db.String(200), default='Использую DeppLink! 🚀')
    theme = db.Column(db.String(20), default='neon-dark')
    status = db.Column(db.String(20), default='offline')
    last_seen = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    chat_type = db.Column(db.String(20), default='private')
    avatar = db.Column(db.Text)
    description = db.Column(db.String(500))
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ChatMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    role = db.Column(db.String(20), default='member')
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(20), default='text')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_deleted = db.Column(db.Boolean, default=False)

class UserTyping(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'))
    is_typing = db.Column(db.Boolean, default=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

class UserSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), unique=True)
    notifications = db.Column(db.Boolean, default=True)
    sounds = db.Column(db.Boolean, default=True)
    auto_download = db.Column(db.Boolean, default=True)
    privacy = db.Column(db.String(20), default='everyone')  # everyone, contacts, nobody
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)

# Создаем таблицы
with app.app_context():
    db.create_all()

# Роуты
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/favicon.ico')
def favicon():
    return send_from_directory('.', 'favicon.ico')

# API
@app.route('/api/check_auth')
def check_auth():
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user:
            user.status = 'online'
            db.session.commit()
            
            # Получаем настройки пользователя
            settings = UserSettings.query.filter_by(user_id=user_id).first()
            if not settings:
                settings = UserSettings(user_id=user_id)
                db.session.add(settings)
                db.session.commit()
            
            return jsonify({
                'authenticated': True,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'avatar': user.avatar,
                    'bio': user.bio,
                    'theme': user.theme,
                    'status': user.status,
                    'last_seen': user.last_seen.isoformat() if user.last_seen else None
                },
                'settings': {
                    'notifications': settings.notifications,
                    'sounds': settings.sounds,
                    'auto_download': settings.auto_download,
                    'privacy': settings.privacy
                }
            })
    return jsonify({'authenticated': False})

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return jsonify({'success': False, 'error': 'Заполните все поля'})
    
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'Имя уже занято'})
    
    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        avatar=f'https://api.dicebear.com/7.x/avataaars/svg?seed={username}&background=0a0a0a&color=00ffff',
        bio='Привет! Я новый пользователь DeppLink 🚀',
        theme='neon-dark',
        status='online'
    )
    
    db.session.add(user)
    db.session.flush()
    
    # Создаем настройки по умолчанию
    settings = UserSettings(user_id=user.id)
    db.session.add(settings)
    
    db.session.commit()
    
    session['user_id'] = user.id
    session.permanent = True
    
    return jsonify({
        'success': True,
        'user': {
            'id': user.id,
            'username': user.username,
            'avatar': user.avatar,
            'bio': user.bio,
            'theme': user.theme,
            'status': user.status
        }
    })

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'success': False, 'error': 'Неверный логин или пароль'})
    
    user.status = 'online'
    user.last_seen = datetime.utcnow()
    db.session.commit()
    
    session['user_id'] = user.id
    session.permanent = True
    
    # Получаем настройки
    settings = UserSettings.query.filter_by(user_id=user.id).first()
    if not settings:
        settings = UserSettings(user_id=user.id)
        db.session.add(settings)
        db.session.commit()
    
    return jsonify({
        'success': True,
        'user': {
            'id': user.id,
            'username': user.username,
            'avatar': user.avatar,
            'bio': user.bio,
            'theme': user.theme,
            'status': user.status,
            'last_seen': user.last_seen.isoformat()
        },
        'settings': {
            'notifications': settings.notifications,
            'sounds': settings.sounds,
            'auto_download': settings.auto_download,
            'privacy': settings.privacy
        }
    })

@app.route('/api/logout', methods=['POST'])
def logout():
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user:
            user.status = 'offline'
            user.last_seen = datetime.utcnow()
            db.session.commit()
    
    session.clear()
    return jsonify({'success': True})

@app.route('/api/user/update', methods=['POST'])
def update_user():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Не авторизован'})
    
    data = request.json
    user = User.query.get(user_id)
    
    if 'username' in data:
        new_username = data['username'].strip()
        if new_username and new_username != user.username:
            if User.query.filter_by(username=new_username).first():
                return jsonify({'success': False, 'error': 'Имя уже занято'})
            user.username = new_username
    
    if 'bio' in data:
        user.bio = data['bio'].strip()
    
    if 'avatar' in data:
        user.avatar = data['avatar']
    
    if 'theme' in data:
        user.theme = data['theme']
    
    db.session.commit()
    
    # Уведомляем об обновлении профиля
    socketio.emit('user_updated', {
        'user_id': user.id,
        'username': user.username,
        'avatar': user.avatar,
        'bio': user.bio,
        'theme': user.theme
    }, broadcast=True)
    
    return jsonify({'success': True})

@app.route('/api/settings/update', methods=['POST'])
def update_settings():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Не авторизован'})
    
    data = request.json
    settings = UserSettings.query.filter_by(user_id=user_id).first()
    
    if not settings:
        settings = UserSettings(user_id=user_id)
        db.session.add(settings)
    
    if 'notifications' in data:
        settings.notifications = bool(data['notifications'])
    
    if 'sounds' in data:
        settings.sounds = bool(data['sounds'])
    
    if 'auto_download' in data:
        settings.auto_download = bool(data['auto_download'])
    
    if 'privacy' in data:
        if data['privacy'] in ['everyone', 'contacts', 'nobody']:
            settings.privacy = data['privacy']
    
    settings.updated_at = datetime.utcnow()
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/api/user/<int:user_id>')
def get_user(user_id):
    current_user_id = session.get('user_id')
    if not current_user_id:
        return jsonify({'success': False, 'error': 'Не авторизован'})
    
    user = User.query.get(user_id)
    if not user:
        return jsonify({'success': False, 'error': 'Пользователь не найден'})
    
    return jsonify({
        'success': True,
        'user': {
            'id': user.id,
            'username': user.username,
            'avatar': user.avatar,
            'bio': user.bio,
            'theme': user.theme,
            'status': user.status,
            'last_seen': user.last_seen.isoformat() if user.last_seen else None
        }
    })

@app.route('/api/users/search')
def search_users():
    query = request.args.get('q', '').strip()
    user_id = session.get('user_id')
    
    if not user_id:
        return jsonify({'success': False, 'error': 'Не авторизован'})
    
    if len(query) < 1:
        return jsonify([])
    
    users = User.query.filter(
        User.username.ilike(f'%{query}%'),
        User.id != user_id
    ).limit(20).all()
    
    return jsonify([{
        'id': u.id,
        'username': u.username,
        'avatar': u.avatar,
        'bio': u.bio,
        'status': u.status
    } for u in users])

@app.route('/api/chats')
def get_chats():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Не авторизован'})
    
    member_chats = ChatMember.query.filter_by(user_id=user_id).all()
    chat_ids = [mc.chat_id for mc in member_chats]
    
    chats = []
    for chat_id in chat_ids:
        chat = Chat.query.get(chat_id)
        if not chat:
            continue
        
        last_message = Message.query.filter_by(
            chat_id=chat_id, 
            is_deleted=False
        ).order_by(Message.created_at.desc()).first()
        
        # Получаем участников для имени
        members = ChatMember.query.filter_by(chat_id=chat_id).all()
        unread_count = 0
        
        if chat.chat_type == 'private' and len(members) == 2:
            other_user_id = next((m.user_id for m in members if m.user_id != user_id), None)
            if other_user_id:
                other_user = User.query.get(other_user_id)
                chat_name = other_user.username if other_user else 'Пользователь'
                chat_avatar = other_user.avatar
            else:
                chat_name = 'Приватный чат'
                chat_avatar = None
        else:
            chat_name = chat.name or 'Группа'
            chat_avatar = chat.avatar
        
        chats.append({
            'id': chat.id,
            'name': chat_name,
            'avatar': chat_avatar,
            'type': chat.chat_type,
            'last_message': {
                'content': last_message.content[:50] + '...' if last_message and len(last_message.content) > 50 else last_message.content if last_message else '',
                'time': last_message.created_at.isoformat() if last_message else '',
                'sender': last_message.user_id if last_message else None
            } if last_message else None,
            'unread_count': unread_count
        })
    
    # Сортируем по времени последнего сообщения
    chats.sort(key=lambda x: x['last_message']['time'] if x['last_message'] else '', reverse=True)
    
    return jsonify(chats)

@app.route('/api/chat/create', methods=['POST'])
def create_chat():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Не авторизован'})
    
    data = request.json
    chat_type = data.get('type', 'private')
    member_ids = data.get('members', [])
    name = data.get('name', '').strip()
    
    if user_id not in member_ids:
        member_ids.append(user_id)
    
    # Для приватного чата проверяем существование
    if chat_type == 'private' and len(member_ids) == 2:
        existing_chat = None
        for chat in Chat.query.filter_by(chat_type='private').all():
            chat_members = [m.user_id for m in ChatMember.query.filter_by(chat_id=chat.id).all()]
            if set(chat_members) == set(member_ids):
                existing_chat = chat
                break
        
        if existing_chat:
            return jsonify({'success': True, 'chat_id': existing_chat.id})
    
    # Создаем чат
    chat = Chat(
        name=name if chat_type == 'group' else '',
        chat_type=chat_type,
        created_by=user_id,
        avatar=data.get('avatar')
    )
    
    db.session.add(chat)
    db.session.flush()
    
    # Добавляем участников
    for member_id in member_ids:
        role = 'admin' if member_id == user_id and chat_type == 'group' else 'member'
        member = ChatMember(chat_id=chat.id, user_id=member_id, role=role)
        db.session.add(member)
    
    db.session.commit()
    
    return jsonify({'success': True, 'chat_id': chat.id})

@app.route('/api/chat/<int:chat_id>')
def get_chat_info(chat_id):
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Не авторизован'})
    
    # Проверяем доступ
    membership = ChatMember.query.filter_by(chat_id=chat_id, user_id=user_id).first()
    if not membership:
        return jsonify({'success': False, 'error': 'Нет доступа'})
    
    chat = Chat.query.get(chat_id)
    members = ChatMember.query.filter_by(chat_id=chat_id).all()
    
    members_info = []
    for member in members:
        user = User.query.get(member.user_id)
        if user:
            members_info.append({
                'id': user.id,
                'username': user.username,
                'avatar': user.avatar,
                'role': member.role
            })
    
    return jsonify({
        'success': True,
        'chat': {
            'id': chat.id,
            'name': chat.name,
            'type': chat.chat_type,
            'avatar': chat.avatar,
            'description': chat.description,
            'members': members_info
        }
    })

@app.route('/api/chat/<int:chat_id>/messages')
def get_chat_messages(chat_id):
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Не авторизован'})
    
    # Проверяем доступ
    membership = ChatMember.query.filter_by(chat_id=chat_id, user_id=user_id).first()
    if not membership:
        return jsonify({'success': False, 'error': 'Нет доступа'})
    
    messages = Message.query.filter_by(
        chat_id=chat_id, 
        is_deleted=False
    ).order_by(Message.created_at.asc()).all()
    
    result = []
    for msg in messages:
        user = User.query.get(msg.user_id)
        result.append({
            'id': msg.id,
            'user_id': msg.user_id,
            'username': user.username if user else 'Неизвестно',
            'avatar': user.avatar if user else None,
            'content': msg.content,
            'type': msg.message_type,
            'created_at': msg.created_at.isoformat(),
            'is_self': msg.user_id == user_id
        })
    
    return jsonify(result)

@app.route('/api/message/delete', methods=['POST'])
def delete_message():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Не авторизован'})
    
    data = request.json
    message_id = data.get('message_id')
    
    message = Message.query.get(message_id)
    if not message or message.user_id != user_id:
        return jsonify({'success': False, 'error': 'Нет прав'})
    
    message.is_deleted = True
    db.session.commit()
    
    # Уведомляем об удалении
    socketio.emit('message_deleted', {
        'message_id': message_id,
        'chat_id': message.chat_id
    }, room=f'chat_{message.chat_id}')
    
    return jsonify({'success': True})

# Socket.IO события
@socketio.on('connect')
def handle_connect():
    user_id = session.get('user_id')
    if user_id:
        join_room(f'user_{user_id}')
        user = User.query.get(user_id)
        if user:
            user.status = 'online'
            db.session.commit()
            
            emit('user_status', {
                'user_id': user_id,
                'status': 'online',
                'username': user.username
            }, broadcast=True, include_self=False)

@socketio.on('disconnect')
def handle_disconnect():
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user:
            user.status = 'offline'
            user.last_seen = datetime.utcnow()
            db.session.commit()
            
            emit('user_status', {
                'user_id': user_id,
                'status': 'offline',
                'username': user.username
            }, broadcast=True, include_self=False)

@socketio.on('join_chat')
def handle_join_chat(data):
    chat_id = data.get('chat_id')
    user_id = session.get('user_id')
    
    if user_id and chat_id:
        join_room(f'chat_{chat_id}')

@socketio.on('leave_chat')
def handle_leave_chat(data):
    chat_id = data.get('chat_id')
    user_id = session.get('user_id')
    
    if user_id and chat_id:
        leave_room(f'chat_{chat_id}')

@socketio.on('send_message')
def handle_send_message(data):
    user_id = session.get('user_id')
    if not user_id:
        return
    
    chat_id = data.get('chat_id')
    content = data.get('content', '').strip()
    message_type = data.get('type', 'text')
    
    if not content or not chat_id:
        return
    
    # Проверяем доступ
    membership = ChatMember.query.filter_by(chat_id=chat_id, user_id=user_id).first()
    if not membership:
        return
    
    # Сохраняем сообщение
    message = Message(
        chat_id=chat_id,
        user_id=user_id,
        content=content,
        message_type=message_type
    )
    db.session.add(message)
    db.session.commit()
    
    user = User.query.get(user_id)
    
    message_data = {
        'id': message.id,
        'chat_id': chat_id,
        'user_id': user_id,
        'username': user.username,
        'avatar': user.avatar,
        'content': content,
        'type': message_type,
        'created_at': message.created_at.isoformat(),
        'is_self': False
    }
    
    # Отправляем всем в чате
    emit('new_message', message_data, room=f'chat_{chat_id}', broadcast=True, include_self=False)
    
    # Отправляем отправителю с флагом is_self
    message_data['is_self'] = True
    emit('new_message', message_data, room=f'user_{user_id}')

@socketio.on('typing_start')
def handle_typing_start(data):
    chat_id = data.get('chat_id')
    user_id = session.get('user_id')
    
    if user_id and chat_id:
        user = User.query.get(user_id)
        
        # Обновляем или создаем запись о печати
        typing = UserTyping.query.filter_by(user_id=user_id, chat_id=chat_id).first()
        if typing:
            typing.is_typing = True
            typing.updated_at = datetime.utcnow()
        else:
            typing = UserTyping(user_id=user_id, chat_id=chat_id, is_typing=True)
            db.session.add(typing)
        
        db.session.commit()
        
        emit('user_typing', {
            'user_id': user_id,
            'username': user.username,
            'chat_id': chat_id,
            'is_typing': True
        }, room=f'chat_{chat_id}', broadcast=True, include_self=False)

@socketio.on('typing_stop')
def handle_typing_stop(data):
    chat_id = data.get('chat_id')
    user_id = session.get('user_id')
    
    if user_id and chat_id:
        typing = UserTyping.query.filter_by(user_id=user_id, chat_id=chat_id).first()
        if typing:
            typing.is_typing = False
            db.session.commit()
        
        emit('user_typing', {
            'user_id': user_id,
            'chat_id': chat_id,
            'is_typing': False
        }, room=f'chat_{chat_id}', broadcast=True, include_self=False)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=10000, allow_unsafe_werkzeug=True)
