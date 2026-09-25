from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from typing import Literal, Optional
from difflib import SequenceMatcher
from datetime import datetime, timezone
import json
import re
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "chat.db"

app = FastAPI(
    title="Bet Code Converter MVP",
    version="0.2.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SAMPLE_CODES = {
    "SP12345": {
        "source": "sportybet",
        "legs": [
            {
                "home": "Arsenal",
                "away": "Chelsea",
                "market": "1X2",
                "pick": "HOME",
                "odds": 1.85
            },
            {
                "home": "Manchester United",
                "away": "Liverpool",
                "market": "GG",
                "pick": "YES",
                "odds": 1.70
            }
        ]
    },

    "BJ99999": {
        "source": "bet9ja",
        "legs": [
            {
                "home": "Barcelona",
                "away": "Real Madrid",
                "market": "O/U 2.5",
                "pick": "OVER",
                "odds": 1.95
            }
        ]
    }
}

MARKET_MAP = {
    "1X2": "Match Result",
    "GG": "Both Teams To Score",
    "GGNG": "Both Teams To Score",
    "NG": "Both Teams To Score",
    "O/U 0.5": "Over/Under 0.5 Goals",
    "O/U 1.5": "Over/Under 1.5 Goals",
    "O/U 2.5": "Over/Under 2.5 Goals",
    "O/U 3.5": "Over/Under 3.5 Goals",
    "O/U 4.5": "Over/Under 4.5 Goals",
    "DC": "Double Chance",
    "DNB": "Draw No Bet",
    "1X": "Double Chance - Home or Draw",
    "X2": "Double Chance - Draw or Away",
    "12": "Double Chance - Home or Away",
    "AH": "Asian Handicap",
    "EH": "European Handicap",
    "CS": "Correct Score",
    "HT/FT": "Half Time / Full Time",
    "OU": "Over/Under Goals",
}

PLATFORM_MARKETS = {
    "bet9ja": [
        "1X2",
        "OU@0.5",
        "OU@1.5",
        "OU@2.5",
        "OU@3.5",
        "OU@4.5",
        "GGNG",
        "DC",
        "DNB",
        "CSFT",
        "MCS3",
        "NGOALS",
        "HAOU@1.5",
        "HAOU@2.5",
        "HAOU@3.5"
    ],

    "sportybet": [
        "Match Result",
        "Both Teams To Score",
        "Over/Under Goals",
        "Double Chance",
        "Draw No Bet",
        "Asian Handicap",
        "European Handicap",
        "Correct Score",
        "Half Time / Full Time"
    ]
}


def clean_code(code: str) -> str:
    return re.sub(r"\s+", "", code or "").upper()


def normalize_team(name: str) -> str:
    s = re.sub(
        r"[^a-z0-9 ]",
        " ",
        (name or "").lower()
    )

    aliases = {
        "man utd": "manchester united",
        "man united": "manchester united",
        "man city": "manchester city",
        "spurs": "tottenham",
        "psg": "paris saint germain",
        "inter milan": "inter",
        "internazionale": "inter",
        "atletico madrid": "atletico"
    }

    s = re.sub(r"\s+", " ", s).strip()

    return aliases.get(s, s)


def similarity(a: str, b: str) -> float:
    return round(
        SequenceMatcher(
            None,
            normalize_team(a),
            normalize_team(b)
        ).ratio() * 100,
        1
    )


def map_market(market: str) -> str:

    raw = (market or "").strip().upper()

    if raw in MARKET_MAP:
        return MARKET_MAP[raw]

    match = re.fullmatch(
        r"OU@([0-9]+(?:\.[0-9]+)?)",
        raw
    )

    if match:
        return f"Over/Under {match.group(1)} Goals"

    return market or "Unknown"


def validate_slip(slip: dict):

    if not isinstance(slip, dict):
        return False, "Slip must be a JSON object."

    legs = slip.get("legs")

    if not isinstance(legs, list) or not legs:
        return False, "Slip must contain at least one leg."

    for i, leg in enumerate(legs, 1):

        if not isinstance(leg, dict):
            return False, f"Leg {i} is invalid."

        for key in ("home", "away", "market", "pick"):

            if not leg.get(key):
                return False, f"Leg {i} is missing '{key}'."

    return True, ""


def convert_slip(
    slip: dict,
    from_platform: str,
    to_platform: str
):

    output = []

    for i, leg in enumerate(
        slip.get("legs", []),
        1
    ):

        target_market = map_market(
            leg.get("market", "")
        )

        output.append({

            "leg": i,

            "home": leg.get(
                "home",
                ""
            ),

            "away": leg.get(
                "away",
                ""
            ),

            "source_market": leg.get(
                "market",
                ""
            ),

            "target_market": target_market,

            "pick": leg.get(
                "pick",
                ""
            ),

            "source_odds": leg.get(
                "odds"
            ),

            "fixture_match": {

                "home_score": 100.0,

                "away_score": 100.0,

                "status":
                    "Demo fixture identity — live fixture lookup is not connected."
            },

            "status":
                "Mapped"
                if target_market != "Unknown"
                else "Needs attention",

            "note":
                "Recheck the live target market and odds before placing."
        })

    return {

        "source": from_platform,

        "target": to_platform,

        "legs": output
    }


def init_db():

    con = sqlite3.connect(DB_PATH)

    con.execute("""
        CREATE TABLE IF NOT EXISTS messages (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            username TEXT NOT NULL,

            message TEXT NOT NULL,

            created_at TEXT NOT NULL
        )
    """)

    con.commit()

    con.close()


init_db()


class ConvertRequest(BaseModel):

    code: Optional[str] = None

    from_platform: Literal[
        "sportybet",
        "bet9ja"
    ]

    to_platform: Literal[
        "sportybet",
        "bet9ja"
    ]

    slip: Optional[dict] = None


class ChatMessage(BaseModel):

    username: str = Field(
        min_length=1,
        max_length=30
    )

    message: str = Field(
        min_length=1,
        max_length=500
    )


@app.get("/")
def home():

    return FileResponse(
        BASE_DIR / "static" / "index.html"
    )


@app.get("/api/health")
def health():

    return {
        "status": "ok",
        "version": "0.2.0"
    }


@app.get("/api/demo-codes")
def demo_codes():

    return {
        "codes": [
            {
                "code": "SP12345",
                "platform": "sportybet"
            },
            {
                "code": "BJ99999",
                "platform": "bet9ja"
            }
        ]
    }


@app.get("/api/markets")
def markets():

    return PLATFORM_MARKETS


@app.post("/api/convert")
def convert(req: ConvertRequest):

    if req.from_platform == req.to_platform:

        return {
            "ok": False,
            "message":
                "Choose two different platforms."
        }

    code = clean_code(
        req.code or ""
    )

    if req.slip is not None:

        slip = req.slip

        source = "manual_json"

    else:

        slip = SAMPLE_CODES.get(
            code
        )

        source = "demo_code"

    if not slip:

        return {
            "ok": False,
            "message":
                "Code is not in the demo dataset. Use SP12345, BJ99999, or paste a slip JSON."
        }

    valid, error = validate_slip(
        slip
    )

    if not valid:

        return {
            "ok": False,
            "message": error
        }

    preview = convert_slip(
        slip,
        req.from_platform,
        req.to_platform
    )

    return {

        "ok": True,

        "mode": "demo",

        "message":
            "Conversion preview generated.",

        "source": source,

        "converted_code": None,

        "converted_code_note":
            "A valid target-platform booking code cannot be fabricated by this app. After checking the mapped slip, recreate/book it on the target platform.",

        "preview": preview
    }


@app.get("/api/chat/history")
def chat_history(
    limit: int = 50
):

    limit = max(
        1,
        min(limit, 100)
    )

    con = sqlite3.connect(
        DB_PATH
    )

    rows = con.execute(
        """
        SELECT username, message, created_at
        FROM messages
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,)
    ).fetchall()

    con.close()

    rows.reverse()

    return {
        "messages": [
            {
                "username": row[0],
                "message": row[1],
                "created_at": row[2]
            }

            for row in rows
        ]
    }


clients = []


@app.websocket("/ws/chat")
async def websocket_endpoint(
    websocket: WebSocket
):

    await websocket.accept()

    clients.append(
        websocket
    )

    try:

        while True:

            raw = await websocket.receive_text()

            try:

                data = ChatMessage.model_validate_json(
                    raw
                )

            except Exception:

                await websocket.send_text(
                    json.dumps({
                        "type": "error",
                        "message":
                            "Invalid chat message."
                    })
                )

                continue

            created_at = datetime.now(
                timezone.utc
            ).isoformat()

            con = sqlite3.connect(
                DB_PATH
            )

            con.execute(
                """
                INSERT INTO messages
                (username, message, created_at)
                VALUES (?, ?, ?)
                """,
                (
                    data.username.strip(),
                    data.message.strip(),
                    created_at
                )
            )

            con.commit()

            con.close()

            payload = json.dumps({

                "type": "message",

                "username":
                    data.username.strip(),

                "message":
                    data.message.strip(),

                "created_at":
                    created_at
            })

            dead = []

            for client in clients:

                try:

                    await client.send_text(
                        payload
                    )

                except Exception:

                    dead.append(
                        client
                    )

            for client in dead:

                if client in clients:

                    clients.remove(
                        client
                    )

    except WebSocketDisconnect:

        if websocket in clients:

            clients.remove(
                websocket
            )
