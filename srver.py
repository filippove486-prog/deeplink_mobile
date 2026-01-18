import os
import json
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, template_folder='.', static_folder='.')
app.config['SECRET_KEY'] = 'deeplink-mega-secret-key-neon'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///deeplink.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PERMANENT_SESSION_LIFETIME'] = 86400 * 365
app.config['SESSION_COOKIE_NAME'] = 'deeplink_session'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')
db = SQLAlchemy(app)

# Модели
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    avatar = db.Column(db.Text, default='https://api.dicebear.com/7.x/avataaars/svg?seed={username}&background=0a0a0a&color=00ffff')
    bio = db.Column(db.String(200), default='Привет! Я использую DeppLink 🚀')
    theme = db.Column(db.String(20), default='neon-cyan')
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_deleted = db.Column(db.Boolean, default=False)

# Создаем таблицы
with app.app_context():
    db.create_all()
    # Создаем тестового пользователя если нет
    if not User.query.first():
        test_user = User(
            username='test',
            password_hash=generate_password_hash('test'),
            bio='Тестовый пользователь'
        )
        db.session.add(test_user)
        db.session.commit()
        print("✅ Создан тестовый пользователь: test/test")

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
    print(f"🔍 Проверка сессии: {user_id}")
    
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
    
    print(f"🔐 Попытка входа: {username}")
    
    user = User.query.filter_by(username=username).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'success': False, 'error': 'Неверный логин или пароль'})
    
    user.status = 'online'
    user.last_seen = datetime.utcnow()
    db.session.commit()
    
    # Важная часть: сохраняем в сессии
    session['user_id'] = user.id
    session.modified = True
    
    print(f"✅ Успешный вход: {username}, ID: {user.id}")
    
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
        bio='Привет! Я новый пользователь DeppLink 🚀'
    )
    
    db.session.add(user)
    db.session.commit()
    
    session['user_id'] = user.id
    session.modified = True
    
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

@app.route('/api/chats')
def get_chats():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify([])
    
    return jsonify([
        {
            'id': 1,
            'name': 'Общий чат',
            'avatar': 'https://api.dicebear.com/7.x/avataaars/svg?seed=General&background=0a0a0a&color=00ffff',
            'last_message': 'Добро пожаловать в DeppLink!',
            'time': datetime.utcnow().isoformat()
        },
        {
            'id': 2,
            'name': 'Тест',
            'avatar': 'https://api.dicebear.com/7.x/avataaars/svg?seed=Test&background=0a0a0a&color=ff00ff',
            'last_message': 'Привет! Как дела?',
            'time': datetime.utcnow().isoformat()
        }
    ])

# Socket.IO
@socketio.on('connect')
def handle_connect():
    print('✅ Новое подключение')
    emit('connected', {'data': 'Connected'})

@socketio.on('send_message')
def handle_message(data):
    print(f"📨 Сообщение: {data}")
    emit('new_message', {
        'id': datetime.utcnow().timestamp(),
        'content': data.get('content', ''),
        'username': 'User',
        'created_at': datetime.utcnow().isoformat(),
        'is_self': False
    }, broadcast=True)

if __name__ == '__main__':
    print("\n" + "="*50)
    print("🚀 DeppLink Messenger запущен!")
    print("🌐 Откройте: http://localhost:10000")
    print("👤 Тестовый аккаунт: test / test")
    print("="*50 + "\n")
    socketio.run(app, host='0.0.0.0', port=10000, debug=True, allow_unsafe_werkzeug=True)
