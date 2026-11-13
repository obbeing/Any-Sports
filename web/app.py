import os
import pymysql
from flask import Flask, abort, render_template

app = Flask(__name__)


def get_conn():
    return pymysql.connect(
        host=os.environ.get("DB_HOST", "db"),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ.get("DB_NAME", "sports"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )


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

    # 종목별로 묶기
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
    finally:
        conn.close()

    return render_template("game.html", game=game, stats=stats)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
