import os
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, template_folder='.', static_folder='.')
app.config['SECRET_KEY'] = 'deeplink-ultimate-neon-messenger-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///deeplink.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 365

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
db = SQLAlchemy(app)

# Модели
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.Text, default='https://api.dicebear.com/7.x/avataaars/svg?seed={username}&background=0a0a0a&color=00ffff')
    bio = db.Column(db.String(200), default='Использую DeppLink 🚀')
    theme = db.Column(db.String(20), default='neon-cyan')
    status = db.Column(db.String(20), default='offline')
    last_seen = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    chat_type = db.Column(db.String(20), default='private')
    avatar = db.Column(db.Text)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_deleted = db.Column(db.Boolean, default=False)

# Создаем таблицы
with app.app_context():
    db.create_all()
    # Создаем тестовые данные
    if not User.query.first():
        # Создаем пользователей
        users_data = [
            ('alex', 'alex123', 'Александр 🎮', 'https://api.dicebear.com/7.x/avataaars/svg?seed=Alex&background=0a0a0a&color=00ffff'),
            ('maria', 'maria123', 'Мария 🌸', 'https://api.dicebear.com/7.x/avataaars/svg?seed=Maria&background=0a0a0a&color=ff00ff'),
            ('max', 'max123', 'Максим 🚀', 'https://api.dicebear.com/7.x/avataaars/svg?seed=Max&background=0a0a0a&color=00ff88'),
            ('anna', 'anna123', 'Анна 💫', 'https://api.dicebear.com/7.x/avataaars/svg?seed=Anna&background=0a0a0a&color=0088ff'),
            ('test', 'test', 'Тестовый аккаунт 🔧', 'https://api.dicebear.com/7.x/avataaars/svg?seed=Test&background=0a0a0a&color=ff6600')
        ]
        
        for username, password, bio, avatar in users_data:
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
                avatar=avatar,
                bio=bio,
                status='online'
            )
            db.session.add(user)
        
        db.session.commit()
        
        # Создаем чаты
        users = User.query.all()
        if len(users) >= 2:
            # Личные чаты
            chat1 = Chat(name='Личный чат', chat_type='private')
            chat2 = Chat(name='Работа', chat_type='private')
            chat3 = Chat(name='Друзья', chat_type='group')
            chat3.avatar = 'https://api.dicebear.com/7.x/avataaars/svg?seed=Friends&background=0a0a0a&color=ff3366'
            
            db.session.add_all([chat1, chat2, chat3])
            db.session.flush()
            
            # Добавляем участников
            members = [
                # Чат 1: test и alex
                ChatMember(chat_id=chat1.id, user_id=users[4].id, role='member'),
                ChatMember(chat_id=chat1.id, user_id=users[0].id, role='member'),
                # Чат 2: test и maria
                ChatMember(chat_id=chat2.id, user_id=users[4].id, role='member'),
                ChatMember(chat_id=chat2.id, user_id=users[1].id, role='member'),
                # Групповой чат: все
                ChatMember(chat_id=chat3.id, user_id=users[4].id, role='admin'),
                ChatMember(chat_id=chat3.id, user_id=users[0].id, role='member'),
                ChatMember(chat_id=chat3.id, user_id=users[1].id, role='member'),
                ChatMember(chat_id=chat3.id, user_id=users[2].id, role='member'),
                ChatMember(chat_id=chat3.id, user_id=users[3].id, role='member')
            ]
            
            db.session.add_all(members)
            
            # Тестовые сообщения
            messages = [
                Message(chat_id=chat1.id, user_id=users[0].id, content='Привет! Как дела?'),
                Message(chat_id=chat1.id, user_id=users[4].id, content='Привет! Всё отлично!'),
                Message(chat_id=chat2.id, user_id=users[1].id, content='Пришли документы по проекту'),
                Message(chat_id=chat3.id, user_id=users[2].id, content='Ребят, кто сегодня будет на встрече?'),
                Message(chat_id=chat3.id, user_id=users[3].id, content='Я буду точно!')
            ]
            
            db.session.add_all(messages)
            db.session.commit()
        
        print("✅ Созданы тестовые данные:")
        print("👤 test / test")
        print("👤 alex / alex123")
        print("👤 maria / maria123")
        print("👤 max / max123")
        print("👤 anna / anna123")

# Мидлварь для сессий
@app.before_request
def make_session_permanent():
    session.permanent = True

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
            
            return jsonify({
                'success': True,
                'authenticated': True,
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'avatar': user.avatar,
                    'bio': user.bio,
                    'theme': user.theme,
                    'status': user.status
                }
            })
    
    return jsonify({'success': True, 'authenticated': False})

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
        bio='Новый пользователь DeppLink 🚀'
    )
    
    db.session.add(user)
    db.session.commit()
    
    session['user_id'] = user.id
    
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
    
    return jsonify({'success': True})

@app.route('/api/user/<int:user_id>')
def get_user(user_id):
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
            'status': user.status
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
    ).limit(10).all()
    
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
    
    # Находим чаты пользователя
    member_chats = ChatMember.query.filter_by(user_id=user_id).all()
    chat_ids = [mc.chat_id for mc in member_chats]
    
    chats = []
    for chat_id in chat_ids:
        chat = Chat.query.get(chat_id)
        if not chat:
            continue
        
        # Получаем последнее сообщение
        last_message = Message.query.filter_by(
            chat_id=chat_id, 
            is_deleted=False
        ).order_by(Message.created_at.desc()).first()
        
        # Для приватных чатов получаем имя собеседника
        if chat.chat_type == 'private':
            members = ChatMember.query.filter_by(chat_id=chat_id).all()
            if len(members) == 2:
                other_user_id = next((m.user_id for m in members if m.user_id != user_id), None)
                if other_user_id:
                    other_user = User.query.get(other_user_id)
                    chat_name = other_user.username if other_user else 'Пользователь'
                    chat_avatar = other_user.avatar
                else:
                    chat_name = 'Приватный чат'
                    chat_avatar = None
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
                'content': last_message.content if last_message else '',
                'time': last_message.created_at.isoformat() if last_message else '',
                'sender': last_message.user_id if last_message else None
            } if last_message else None,
            'unread': 0
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
    
    # Для приватных чатов проверяем существование
    if chat_type == 'private' and len(member_ids) == 2:
        existing = None
        for chat in Chat.query.filter_by(chat_type='private').all():
            chat_members = [m.user_id for m in ChatMember.query.filter_by(chat_id=chat.id).all()]
            if set(chat_members) == set(member_ids):
                existing = chat
                break
        
        if existing:
            return jsonify({'success': True, 'chat_id': existing.id})
    
    # Создаем новый чат
    chat = Chat(
        name=name if chat_type == 'group' else '',
        chat_type=chat_type,
        created_by=user_id
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
            'created_at': msg.created_at.isoformat(),
            'is_self': msg.user_id == user_id
        })
    
    return jsonify(result)

@app.route('/api/message/send', methods=['POST'])
def send_message():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'error': 'Не авторизован'})
    
    data = request.json
    chat_id = data.get('chat_id')
    content = data.get('content', '').strip()
    
    if not content or not chat_id:
        return jsonify({'success': False, 'error': 'Неверные данные'})
    
    # Проверяем доступ
    membership = ChatMember.query.filter_by(chat_id=chat_id, user_id=user_id).first()
    if not membership:
        return jsonify({'success': False, 'error': 'Нет доступа'})
    
    # Сохраняем сообщение
    message = Message(
        chat_id=chat_id,
        user_id=user_id,
        content=content
    )
    
    db.session.add(message)
    db.session.commit()
    
    # Получаем данные пользователя
    user = User.query.get(user_id)
    
    return jsonify({
        'success': True,
        'message': {
            'id': message.id,
            'chat_id': chat_id,
            'user_id': user_id,
            'username': user.username,
            'avatar': user.avatar,
            'content': content,
            'created_at': message.created_at.isoformat(),
            'is_self': True
        }
    })

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
    
    return jsonify({'success': True})

# Socket.IO
@socketio.on('connect')
def handle_connect():
    user_id = session.get('user_id')
    if user_id:
        join_room(f'user_{user_id}')
        user = User.query.get(user_id)
        if user:
            user.status = 'online'
            db.session.commit()

@socketio.on('disconnect')
def handle_disconnect():
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user:
            user.status = 'offline'
            user.last_seen = datetime.utcnow()
            db.session.commit()

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
        content=content
    )
    
    db.session.add(message)
    db.session.commit()
    
    # Получаем данные пользователя
    user = User.query.get(user_id)
    
    message_data = {
        'id': message.id,
        'chat_id': chat_id,
        'user_id': user_id,
        'username': user.username,
        'avatar': user.avatar,
        'content': content,
        'created_at': message.created_at.isoformat(),
        'is_self': False
    }
    
    # Отправляем в комнату чата
    emit('new_message', message_data, room=f'chat_{chat_id}', broadcast=True, include_self=False)
    
    # Отправляем отправителю
    message_data['is_self'] = True
    emit('new_message', message_data, room=f'user_{user_id}')

@socketio.on('typing_start')
def handle_typing_start(data):
    chat_id = data.get('chat_id')
    user_id = session.get('user_id')
    
    if user_id and chat_id:
        user = User.query.get(user_id)
        
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
        emit('user_typing', {
            'user_id': user_id,
            'chat_id': chat_id,
            'is_typing': False
        }, room=f'chat_{chat_id}', broadcast=True, include_self=False)

@socketio.on('delete_message')
def handle_delete_message(data):
    message_id = data.get('message_id')
    user_id = session.get('user_id')
    
    if not user_id or not message_id:
        return
    
    message = Message.query.get(message_id)
    if not message or message.user_id != user_id:
        return
    
    message.is_deleted = True
    db.session.commit()
    
    emit('message_deleted', {
        'message_id': message_id,
        'chat_id': message.chat_id
    }, room=f'chat_{message.chat_id}', broadcast=True)

if __name__ == '__main__':
    print("\n" + "="*60)
    print("🚀 DEEPLINK MESSENGER ЗАПУЩЕН!")
    print("="*60)
    print("🌐 Откройте в браузере: http://localhost:10000")
    print("\n📱 Тестовые аккаунты:")
    print("├── 👤 test / test")
    print("├── 👤 alex / alex123")
    print("├── 👤 maria / maria123")
    print("├── 👤 max / max123")
    print("└── 👤 anna / anna123")
    print("\n💫 Все функции активны!")
    print("="*60 + "\n")
    
    socketio.run(app, host='0.0.0.0', port=10000, debug=True, allow_unsafe_werkzeug=True)
