import json
import logging
import os
import re
import sys
from datetime import datetime, timezone

import pymysql
from flask import (Flask, abort, flash, redirect, render_template, request,
                   session)
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or None
if not app.secret_key:
    raise RuntimeError("SECRET_KEY 환경변수가 필요합니다 (.env에 SECRET_KEY를 추가하세요)")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

# 앱 이벤트 로그: JSON 한 줄씩 stdout과 파일에 남긴다 (ELK가 파일을 수집)
LOG_DIR = os.environ.get("APP_LOG_DIR", "/var/log/app")
log = logging.getLogger("sports")
log.setLevel(logging.INFO)
log.propagate = False
_fmt = logging.Formatter("%(message)s")
_sh = logging.StreamHandler(sys.stdout)
_sh.setFormatter(_fmt)
log.addHandler(_sh)
try:
    os.makedirs(LOG_DIR, exist_ok=True)
    _fh = logging.FileHandler(os.path.join(LOG_DIR, "app.json.log"), encoding="utf-8")
    _fh.setFormatter(_fmt)
    log.addHandler(_fh)
except OSError:
    pass  # 로그 디렉터리를 쓸 수 없어도 서비스는 계속 동작한다


def log_event(level, event, **fields):
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "level": level.upper(),
        "event": event,
    }
    record.update(fields)
    log.log(getattr(logging, level.upper()), json.dumps(record, ensure_ascii=False))

BANNED_FILE = os.path.join(os.path.dirname(__file__), "banned_words.txt")
USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,30}$")


# ---------- 공통 함수 ----------
def get_conn():
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "db"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ.get("DB_NAME", "sports"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


def client_ip():
    xff = request.headers.get("X-Forwarded-For", "")
    return xff.split(",")[0].strip() if xff else request.remote_addr


def clean(value, limit=50):
    """로그에 넣을 값에서 줄바꿈 등을 제거한다 (로그 위조 방지)."""
    return re.sub(r"[\r\n\t]", " ", value)[:limit]


def load_banned_words():
    with open(BANNED_FILE, encoding="utf-8") as f:
        return [w.strip() for w in f if w.strip()]


def find_banned_word(text):
    """공백을 제거하고 소문자로 바꿔 금칙어와 비교한다 ('도 박' 같은 우회 대응)."""
    normalized = re.sub(r"\s+", "", text).lower()
    for word in load_banned_words():
        if word.lower() in normalized:
            return word
    return None


@app.context_processor
def inject_user():
    return {"current_user": session.get("username")}


# ---------- 메인 / 상세 / 검색 ----------
@app.route("/")
def index():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT g.id, s.name AS sport, g.home_team, g.away_team,
                       g.home_score, g.away_score, g.status, g.played_at
                FROM games g
                JOIN sports s ON s.id = g.sport_id
                ORDER BY s.id, g.played_at
                """
            )
            rows = cur.fetchall()
    finally:
        conn.close()

    games_by_sport = {}
    for row in rows:
        games_by_sport.setdefault(row["sport"], []).append(row)
    return render_template("index.html", games_by_sport=games_by_sport)


@app.route("/game/<int:game_id>")
def game_detail(game_id):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT g.id, s.name AS sport, g.home_team, g.away_team,
                       g.home_score, g.away_score, g.status, g.played_at
                FROM games g
                JOIN sports s ON s.id = g.sport_id
                WHERE g.id = %s
                """,
                (game_id,),
            )
            game = cur.fetchone()
            if game is None:
                abort(404)

            cur.execute(
                """
                SELECT p.name, p.team, ps.stat_name, ps.stat_value
                FROM player_stats ps
                JOIN players p ON p.id = ps.player_id
                WHERE ps.game_id = %s
                ORDER BY p.team, p.name, ps.id
                """,
                (game_id,),
            )
            stats = cur.fetchall()

            # 격리된 댓글은 화면에 보여주지 않는다
            cur.execute(
                """
                SELECT c.content, c.created_at, u.username
                FROM comments c
                JOIN users u ON u.id = c.user_id
                WHERE c.game_id = %s AND c.status = '정상'
                ORDER BY c.id DESC
                LIMIT 50
                """,
                (game_id,),
            )
            comments = cur.fetchall()
    finally:
        conn.close()

    return render_template("game.html", game=game, stats=stats, comments=comments)


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    games, players = [], []

    if q:
        like = f"%{q}%"
        conn = get_conn()
        try:
            with conn.cursor() as cur:
                # 사용자 입력은 반드시 %s 파라미터로 전달한다 (SQL Injection 방지)
                cur.execute(
                    """
                    SELECT g.id, s.name AS sport, g.home_team, g.away_team,
                           g.home_score, g.away_score, g.status, g.played_at
                    FROM games g
                    JOIN sports s ON s.id = g.sport_id
                    WHERE g.home_team LIKE %s OR g.away_team LIKE %s
                    ORDER BY g.played_at
                    LIMIT 20
                    """,
                    (like, like),
                )
                games = cur.fetchall()

                cur.execute(
                    """
                    SELECT p.id, p.name, p.team, s.name AS sport
                    FROM players p
                    JOIN sports s ON s.id = p.sport_id
                    WHERE p.name LIKE %s OR p.team LIKE %s
                    ORDER BY p.name
                    LIMIT 20
                    """,
                    (like, like),
                )
                players = cur.fetchall()
        finally:
            conn.close()

    return render_template("search.html", q=q, games=games, players=players)


# ---------- 회원가입 / 로그인 / 로그아웃 ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not USERNAME_RE.match(username):
            flash("아이디는 영문, 숫자, 밑줄(_)로 3~30자여야 합니다.")
            return render_template("auth.html", mode="register"), 400
        if len(password) < 6:
            flash("비밀번호는 6자 이상이어야 합니다.")
            return render_template("auth.html", mode="register"), 400

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                    (username, generate_password_hash(password)),
                )
            conn.commit()
        except pymysql.err.IntegrityError:
            flash("이미 사용 중인 아이디입니다.")
            return render_template("auth.html", mode="register"), 409
        finally:
            conn.close()

        log_event("info", "register", user=clean(username), ip=client_ip())
        flash("가입이 완료되었습니다. 로그인해 주세요.")
        return redirect("/login")

    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, password_hash FROM users WHERE username = %s",
                    (username,),
                )
                user = cur.fetchone()
        finally:
            conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = username
            log_event("info", "login_ok", user=clean(username), ip=client_ip())
            return redirect("/")

        # 실패 로그는 탐지 규칙(무차별 대입)의 핵심 재료
        log_event("warning", "login_fail", user=clean(username), ip=client_ip())
        flash("아이디 또는 비밀번호가 올바르지 않습니다.")
        return render_template("auth.html", mode="login"), 401

    return render_template("auth.html", mode="login")


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/")


# ---------- 댓글 ----------
@app.route("/game/<int:game_id>/comment", methods=["POST"])
def add_comment(game_id):
    if "user_id" not in session:
        flash("로그인 후 댓글을 남길 수 있습니다.")
        return redirect("/login")

    content = request.form.get("content", "").strip()
    if not content:
        flash("댓글 내용을 입력해 주세요.")
        return redirect(f"/game/{game_id}")
    if len(content) > 300:
        flash("댓글은 300자 이하로 작성해 주세요.")
        return redirect(f"/game/{game_id}")

    banned = find_banned_word(content)
    status = "격리" if banned else "정상"

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM games WHERE id = %s", (game_id,))
            if cur.fetchone() is None:
                abort(404)
            cur.execute(
                "INSERT INTO comments (game_id, user_id, content, status) "
                "VALUES (%s, %s, %s, %s)",
                (game_id, session["user_id"], content, status),
            )
        conn.commit()
    finally:
        conn.close()

    if banned:
        log_event("warning", "comment_quarantined", user=clean(session["username"]),
                  game=game_id, word=banned, ip=client_ip())
        flash("금칙어가 포함되어 댓글이 검토 대기 상태로 처리되었습니다.")
    else:
        log_event("info", "comment_ok", user=clean(session["username"]),
                  game=game_id, ip=client_ip())
    return redirect(f"/game/{game_id}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
