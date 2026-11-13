-- 스포츠 점수/키워드/스탯 사이트 초기 스키마 + 더미 데이터
SET NAMES utf8mb4;

CREATE TABLE sports (
  id   INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(20) NOT NULL UNIQUE
);

CREATE TABLE games (
  id          INT AUTO_INCREMENT PRIMARY KEY,
  sport_id    INT NOT NULL,
  home_team   VARCHAR(50) NOT NULL,
  away_team   VARCHAR(50) NOT NULL,
  home_score  INT DEFAULT 0,
  away_score  INT DEFAULT 0,
  status      ENUM('예정','진행중','종료') DEFAULT '예정',
  played_at   DATETIME NOT NULL,
  FOREIGN KEY (sport_id) REFERENCES sports(id)
);

CREATE TABLE players (
  id       INT AUTO_INCREMENT PRIMARY KEY,
  sport_id INT NOT NULL,
  name     VARCHAR(50) NOT NULL,
  team     VARCHAR(50) NOT NULL,
  FOREIGN KEY (sport_id) REFERENCES sports(id)
);

CREATE TABLE player_stats (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  player_id  INT NOT NULL,
  game_id    INT NOT NULL,
  stat_name  VARCHAR(30) NOT NULL,
  stat_value DECIMAL(6,1) NOT NULL,
  FOREIGN KEY (player_id) REFERENCES players(id),
  FOREIGN KEY (game_id) REFERENCES games(id)
);

CREATE TABLE users (
  id            INT AUTO_INCREMENT PRIMARY KEY,
  username      VARCHAR(30) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE comments (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  game_id    INT NOT NULL,
  user_id    INT NOT NULL,
  content    TEXT NOT NULL,
  status     ENUM('정상','격리') DEFAULT '정상',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (game_id) REFERENCES games(id),
  FOREIGN KEY (user_id) REFERENCES users(id)
);

-- 더미 데이터 (가상의 팀/선수)
INSERT INTO sports (name) VALUES ('축구'), ('야구'), ('농구');

INSERT INTO games (sport_id, home_team, away_team, home_score, away_score, status, played_at) VALUES
(1, '서울FC', '부산유나이티드', 2, 1, '종료', '2026-11-14 14:00:00'),
(1, '인천시티', '대전웨이브', 0, 0, '진행중', '2026-11-14 16:30:00'),
(2, '서울베어스', '대구라이온즈', 5, 3, '종료', '2026-11-14 13:00:00'),
(2, '부산자이언츠', '광주타이거즈', 1, 4, '종료', '2026-11-14 13:00:00'),
(3, '서울썬더스', '울산모비스', 78, 74, '종료', '2026-11-14 15:00:00'),
(3, '부산KCC', '수원소닉붐', 0, 0, '예정', '2026-11-14 19:00:00');

INSERT INTO players (sport_id, name, team) VALUES
(1, '김민준', '서울FC'),
(1, '이도윤', '부산유나이티드'),
(2, '박서준', '서울베어스'),
(2, '최하준', '광주타이거즈'),
(3, '정우진', '서울썬더스'),
(3, '강시우', '울산모비스');

INSERT INTO player_stats (player_id, game_id, stat_name, stat_value) VALUES
(1, 1, '득점', 2),
(1, 1, '어시스트', 0),
(2, 1, '득점', 1),
(3, 3, '안타', 3),
(3, 3, '타점', 2),
(4, 4, '탈삼진', 9),
(5, 5, '득점', 28.0),
(5, 5, '리바운드', 9),
(6, 5, '득점', 22.0);
