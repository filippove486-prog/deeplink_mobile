from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import json
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-in-production'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///messenger.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

# Модели базы данных
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    nickname = db.Column(db.String(80), nullable=False)
    avatar = db.Column(db.String(200), default='default_avatar.png')
    status = db.Column(db.String(100), default='В сети')
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    privacy = db.Column(db.String(20), default='public')  # public/private
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_online = db.Column(db.Boolean, default=False)
    
class Chat(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    is_group = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
class ChatMember(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    joined_at = db.Column(db.DateTime, default=datetime.utcnow)

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    
class TypingIndicator(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.Integer, db.ForeignKey('chat.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    is_typing = db.Column(db.Boolean, default=False)

# Создаем таблицы
with app.app_context():
    db.create_all()

# Хранилище для typing indicators в памяти
typing_users = {}

# Маршруты
@app.route('/')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            user.is_online = True
            db.session.commit()
            return jsonify({'success': True, 'user': {
                'id': user.id,
                'username': user.username,
                'nickname': user.nickname,
                'avatar': user.avatar
            }})
        
        return jsonify({'success': False, 'error': 'Неверный логин или пароль'})
    
    return render_template('login.html')

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    nickname = data.get('nickname')
    
    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'Имя пользователя уже занято'})
    
    if password == username:
        return jsonify({'success': False, 'error': 'Пароль не может совпадать с именем пользователя'})
    
    if User.query.filter_by(nickname=nickname).first():
        return jsonify({'success': False, 'error': 'Такой никнейм уже существует'})
    
    user = User(
        username=username,
        password_hash=generate_password_hash(password),
        nickname=nickname
    )
    
    db.session.add(user)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/logout')
def logout():
    if 'user_id' in session:
        user_id = session['user_id']
        user = User.query.get(user_id)
        if user:
            user.is_online = False
            user.last_seen = datetime.utcnow()
            db.session.commit()
        session.clear()
    return redirect(url_for('login'))

@app.route('/api/user')
def get_user():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user = User.query.get(session['user_id'])
    return jsonify({
        'id': user.id,
        'username': user.username,
        'nickname': user.nickname,
        'avatar': user.avatar,
        'status': user.status,
        'privacy': user.privacy
    })

@app.route('/api/search')
def search_users():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    query = request.args.get('q', '')
    users = User.query.filter(
        (User.username.contains(query)) | (User.nickname.contains(query))
    ).limit(20).all()
    
    result = []
    for user in users:
        if user.id != session['user_id']:
            result.append({
                'id': user.id,
                'username': user.username,
                'nickname': user.nickname,
                'avatar': user.avatar,
                'status': user.status,
                'is_online': user.is_online
            })
    
    return jsonify(result)

@app.route('/api/chats')
def get_chats():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    user_id = session['user_id']
    chats = Chat.query.join(ChatMember).filter(ChatMember.user_id == user_id).all()
    
    result = []
    for chat in chats:
        last_message = Message.query.filter_by(chat_id=chat.id).order_by(Message.timestamp.desc()).first()
        unread_count = Message.query.filter_by(chat_id=chat.id, is_read=False).count()
        
        result.append({
            'id': chat.id,
            'name': chat.name,
            'is_group': chat.is_group,
            'last_message': last_message.content if last_message else '',
            'timestamp': last_message.timestamp.isoformat() if last_message else '',
            'unread': unread_count
        })
    
    return jsonify(result)

@app.route('/api/chat/<int:chat_id>/messages')
def get_messages(chat_id):
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    messages = Message.query.filter_by(chat_id=chat_id).order_by(Message.timestamp).all()
    
    result = []
    for msg in messages:
        user = User.query.get(msg.user_id)
        result.append({
            'id': msg.id,
            'content': msg.content,
            'timestamp': msg.timestamp.isoformat(),
            'user': {
                'id': user.id,
                'nickname': user.nickname,
                'avatar': user.avatar
            }
        })
    
    # Помечаем сообщения как прочитанные
    Message.query.filter_by(chat_id=chat_id, is_read=False).update({'is_read': True})
    db.session.commit()
    
    return jsonify(result)

@app.route('/api/user/update', methods=['POST'])
def update_profile():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    user = User.query.get(session['user_id'])
    
    if 'nickname' in data and data['nickname'] != user.nickname:
        if User.query.filter_by(nickname=data['nickname']).first():
            return jsonify({'success': False, 'error': 'Никнейм уже занят'})
        user.nickname = data['nickname']
    
    if 'status' in data:
        user.status = data['status']
    
    if 'privacy' in data:
        user.privacy = data['privacy']
    
    db.session.commit()
    return jsonify({'success': True})

@app.route('/api/chat/create', methods=['POST'])
def create_chat():
    if 'user_id' not in session:
        return jsonify({'error': 'Not authenticated'}), 401
    
    data = request.get_json()
    user_id = session['user_id']
    target_user_id = data.get('user_id')
    
    # Проверяем, существует ли уже чат
    existing_chat = db.session.query(Chat).join(ChatMember).filter(
        ChatMember.user_id == user_id,
        Chat.id.in_(
            db.session.query(ChatMember.chat_id).filter(ChatMember.user_id == target_user_id)
        )
    ).first()
    
    if existing_chat:
        return jsonify({'success': True, 'chat_id': existing_chat.id})
    
    # Создаем новый чат
    target_user = User.query.get(target_user_id)
    chat = Chat(name=f"{user_id}_{target_user_id}", is_group=False)
    db.session.add(chat)
    db.session.commit()
    
    # Добавляем участников
    chat_member1 = ChatMember(chat_id=chat.id, user_id=user_id)
    chat_member2 = ChatMember(chat_id=chat.id, user_id=target_user_id)
    db.session.add_all([chat_member1, chat_member2])
    db.session.commit()
    
    return jsonify({'success': True, 'chat_id': chat.id})

# WebSocket события
@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        user_id = session['user_id']
        user = User.query.get(user_id)
        if user:
            user.is_online = True
            db.session.commit()
            emit('user_status', {'user_id': user_id, 'is_online': True}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        user_id = session['user_id']
        user = User.query.get(user_id)
        if user:
            user.is_online = False
            user.last_seen = datetime.utcnow()
            db.session.commit()
            emit('user_status', {'user_id': user_id, 'is_online': False}, broadcast=True)

@socketio.on('join_chat')
def handle_join_chat(data):
    chat_id = data['chat_id']
    join_room(f'chat_{chat_id}')

@socketio.on('leave_chat')
def handle_leave_chat(data):
    chat_id = data['chat_id']
    leave_room(f'chat_{chat_id}')

@socketio.on('send_message')
def handle_send_message(data):
    chat_id = data['chat_id']
    content = data['content']
    user_id = session['user_id']
    
    message = Message(
        chat_id=chat_id,
        user_id=user_id,
        content=content
    )
    db.session.add(message)
    db.session.commit()
    
    user = User.query.get(user_id)
    
    emit('new_message', {
        'chat_id': chat_id,
        'message': {
            'id': message.id,
            'content': content,
            'timestamp': message.timestamp.isoformat(),
            'user': {
                'id': user_id,
                'nickname': user.nickname,
                'avatar': user.avatar
            }
        }
    }, room=f'chat_{chat_id}')

@socketio.on('typing')
def handle_typing(data):
    chat_id = data['chat_id']
    is_typing = data['is_typing']
    user_id = session['user_id']
    
    user = User.query.get(user_id)
    
    emit('user_typing', {
        'chat_id': chat_id,
        'user_id': user_id,
        'user_nickname': user.nickname,
        'is_typing': is_typing
    }, room=f'chat_{chat_id}')

if __name__ == '__main__':
    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
