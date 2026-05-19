"""
Chess Move Validation Microservice
CS 361 - Microservice A

COMMUNICATION PIPE: gRPC over TCP port 50051
─────────────────────────────────────────────────────────────
This file and test_client.py do NOT import each other.
They communicate exclusively through the gRPC network pipe:

  test_client.py  ──[gRPC request]──►  server.py
  test_client.py  ◄─[gRPC response]──  server.py

The contract between them is defined solely in chess.proto.
─────────────────────────────────────────────────────────────
"""

import grpc
import json
import time
import logging
from concurrent import futures

import chess_pb2
import chess_pb2_grpc

logging.basicConfig(level=logging.INFO, format="[SERVER] %(message)s")
log = logging.getLogger(__name__)

# ── Board helpers ──────────────────────────────────────────────────────────────

def pos_to_rc(pos: str):
    """Convert chess notation (e.g. 'E2') to (row, col) with A1 = (0,0)."""
    col = ord(pos[0].upper()) - ord('A')   # A=0 … H=7
    row = int(pos[1]) - 1                  # 1=0 … 8=7
    return row, col

def default_board():
    """Return a standard starting position as a dict {pos: piece}."""
    board = {}
    back_rank = ['ROOK','KNIGHT','BISHOP','QUEEN','KING','BISHOP','KNIGHT','ROOK']
    files = 'ABCDEFGH'
    for i, piece in enumerate(back_rank):
        board[f"{files[i]}1"] = f"WHITE_{piece}"
        board[f"{files[i]}8"] = f"BLACK_{piece}"
    for f in files:
        board[f"{f}2"] = "WHITE_PAWN"
        board[f"{f}7"] = "BLACK_PAWN"
    return board

# ── Validation logic ───────────────────────────────────────────────────────────

def validate_move(piece: str, src: str, dst: str, board: dict, move_type: str):
    """
    Core chess rules. Returns (is_valid, error_message).
    Covers: pawn, rook, bishop, queen, knight, king, and special moves.
    """
    if piece is None:
        return False, f"No piece at {src}"

    color, kind = piece.split("_", 1)
    sr, sc = pos_to_rc(src)
    dr, dc = pos_to_rc(dst)
    row_diff = dr - sr
    col_diff = dc - sc

    # Can't capture your own piece
    target = board.get(dst)
    if target and target.startswith(color):
        return False, f"Cannot capture your own piece at {dst}"

    if kind == "PAWN":
        direction = 1 if color == "WHITE" else -1
        start_row = 1 if color == "WHITE" else 6

        if col_diff == 0:  # forward move
            if row_diff == direction and not board.get(dst):
                return True, ""
            if row_diff == 2 * direction and sr == start_row and not board.get(dst):
                mid = f"{src[0]}{sr + direction + 1}"
                if not board.get(mid):
                    return True, ""
            return False, "Invalid pawn move"
        elif abs(col_diff) == 1 and row_diff == direction:
            if move_type == "EN_PASSANT" or board.get(dst):
                return True, ""
            return False, "Pawn can only move diagonally when capturing"
        return False, "Invalid pawn move"

    elif kind == "ROOK":
        if row_diff != 0 and col_diff != 0:
            return False, "Rook must move in a straight line"
        # Check path clear
        r_step = (1 if row_diff > 0 else -1) if row_diff != 0 else 0
        c_step = (1 if col_diff > 0 else -1) if col_diff != 0 else 0
        r, c = sr + r_step, sc + c_step
        files = 'ABCDEFGH'
        while (r, c) != (dr, dc):
            sq = f"{files[c]}{r+1}"
            if board.get(sq):
                return False, f"Path blocked at {sq}"
            r += r_step
            c += c_step
        return True, ""

    elif kind == "BISHOP":
        if abs(row_diff) != abs(col_diff):
            return False, "Bishop must move diagonally"
        r_step = 1 if row_diff > 0 else -1
        c_step = 1 if col_diff > 0 else -1
        r, c = sr + r_step, sc + c_step
        files = 'ABCDEFGH'
        while (r, c) != (dr, dc):
            sq = f"{files[c]}{r+1}"
            if board.get(sq):
                return False, f"Path blocked at {sq}"
            r += r_step
            c += c_step
        return True, ""

    elif kind == "QUEEN":
        straight = row_diff == 0 or col_diff == 0
        diagonal = abs(row_diff) == abs(col_diff)
        if not (straight or diagonal):
            return False, "Queen must move straight or diagonally"
        # Reuse rook/bishop path logic
        r_step = (0 if row_diff == 0 else (1 if row_diff > 0 else -1))
        c_step = (0 if col_diff == 0 else (1 if col_diff > 0 else -1))
        r, c = sr + r_step, sc + c_step
        files = 'ABCDEFGH'
        while (r, c) != (dr, dc):
            sq = f"{files[c]}{r+1}"
            if board.get(sq):
                return False, f"Path blocked at {sq}"
            r += r_step
            c += c_step
        return True, ""

    elif kind == "KNIGHT":
        if sorted([abs(row_diff), abs(col_diff)]) != [1, 2]:
            return False, "Knight must move in an L-shape"
        return True, ""

    elif kind == "KING":
        if move_type == "CASTLE":
            return True, ""  # Simplified: trust caller flagged it correctly
        if abs(row_diff) <= 1 and abs(col_diff) <= 1 and (row_diff, col_diff) != (0, 0):
            return True, ""
        return False, "King can only move one square"

    return False, f"Unknown piece type: {kind}"


def apply_move(board: dict, src: str, dst: str, piece: str, move_type: str):
    """Return a new board dict with the move applied."""
    new_board = dict(board)
    new_board[dst] = piece
    del new_board[src]

    # En passant: remove the captured pawn
    if move_type == "EN_PASSANT":
        captured_row = str(int(dst[1]) + (-1 if piece.startswith("WHITE") else 1))
        new_board.pop(f"{dst[0]}{captured_row}", None)

    return new_board


def king_in_check(board: dict, color: str):
    """Return True if 'color' king is under attack."""
    king_sq = next((sq for sq, p in board.items() if p == f"{color}_KING"), None)
    if not king_sq:
        return False
    opponent = "BLACK" if color == "WHITE" else "WHITE"
    for sq, piece in board.items():
        if piece.startswith(opponent):
            ok, _ = validate_move(piece, sq, king_sq, board, "NORMAL")
            if ok:
                return True
    return False


# ── gRPC service implementation ────────────────────────────────────────────────

class MoveValidatorServicer(chess_pb2_grpc.MoveValidatorServicer):

    def ValidateMove(self, request, context):
        log.info(f"Request  game={request.game_id} player={request.player_id} "
                 f"{request.piece_position}→{request.target_position} ({request.move_type})")

        # Decode board state
        try:
            board = json.loads(request.board_state) if request.board_state else default_board()
        except json.JSONDecodeError:
            board = default_board()

        src = request.piece_position.upper()
        dst = request.target_position.upper()
        piece = board.get(src)

        # Run validation
        is_valid, error = validate_move(piece, src, dst, board, request.move_type)

        updated_board = board
        check_state = False
        checkmate = False

        if is_valid:
            updated_board = apply_move(board, src, dst, piece, request.move_type)
            opponent = "BLACK" if piece.startswith("WHITE") else "WHITE"
            check_state = king_in_check(updated_board, opponent)

            # Self-check: illegal if your own king ends up in check
            mover_color = piece.split("_")[0]
            if king_in_check(updated_board, mover_color):
                is_valid = False
                error = "Move leaves your king in check"
                updated_board = board

        result = chess_pb2.ValidateMoveResponse(
            is_valid=is_valid,
            move_type=request.move_type,
            check_state=check_state,
            checkmate=checkmate,
            updated_board=json.dumps(updated_board),
            error_message=error,
        )

        log.info(f"Response valid={is_valid} check={check_state} error='{error}'")
        return result


# ── Entry point ────────────────────────────────────────────────────────────────

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chess_pb2_grpc.add_MoveValidatorServicer_to_server(MoveValidatorServicer(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    log.info("Microservice listening on port 50051  (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        server.stop(0)

if __name__ == "__main__":
    serve()
"""
Chess Move Validation Microservice
CS 361 - Microservice A

Runs a gRPC server on port 50051.
Validates chess moves according to piece movement rules.
"""

import grpc
import json
import time
import logging
from concurrent import futures

import chess_pb2
import chess_pb2_grpc

logging.basicConfig(level=logging.INFO, format="[SERVER] %(message)s")
log = logging.getLogger(__name__)

# ── Board helpers ──────────────────────────────────────────────────────────────

def pos_to_rc(pos: str):
    """Convert chess notation (e.g. 'E2') to (row, col) with A1 = (0,0)."""
    col = ord(pos[0].upper()) - ord('A')   # A=0 … H=7
    row = int(pos[1]) - 1                  # 1=0 … 8=7
    return row, col

def default_board():
    """Return a standard starting position as a dict {pos: piece}."""
    board = {}
    back_rank = ['ROOK','KNIGHT','BISHOP','QUEEN','KING','BISHOP','KNIGHT','ROOK']
    files = 'ABCDEFGH'
    for i, piece in enumerate(back_rank):
        board[f"{files[i]}1"] = f"WHITE_{piece}"
        board[f"{files[i]}8"] = f"BLACK_{piece}"
    for f in files:
        board[f"{f}2"] = "WHITE_PAWN"
        board[f"{f}7"] = "BLACK_PAWN"
    return board

# ── Validation logic ───────────────────────────────────────────────────────────

def validate_move(piece: str, src: str, dst: str, board: dict, move_type: str):
    """
    Core chess rules. Returns (is_valid, error_message).
    Covers: pawn, rook, bishop, queen, knight, king, and special moves.
    """
    if piece is None:
        return False, f"No piece at {src}"

    color, kind = piece.split("_", 1)
    sr, sc = pos_to_rc(src)
    dr, dc = pos_to_rc(dst)
    row_diff = dr - sr
    col_diff = dc - sc

    # Can't capture your own piece
    target = board.get(dst)
    if target and target.startswith(color):
        return False, f"Cannot capture your own piece at {dst}"

    if kind == "PAWN":
        direction = 1 if color == "WHITE" else -1
        start_row = 1 if color == "WHITE" else 6

        if col_diff == 0:  # forward move
            if row_diff == direction and not board.get(dst):
                return True, ""
            if row_diff == 2 * direction and sr == start_row and not board.get(dst):
                mid = f"{src[0]}{sr + direction + 1}"
                if not board.get(mid):
                    return True, ""
            return False, "Invalid pawn move"
        elif abs(col_diff) == 1 and row_diff == direction:
            if move_type == "EN_PASSANT" or board.get(dst):
                return True, ""
            return False, "Pawn can only move diagonally when capturing"
        return False, "Invalid pawn move"

    elif kind == "ROOK":
        if row_diff != 0 and col_diff != 0:
            return False, "Rook must move in a straight line"
        # Check path clear
        r_step = (1 if row_diff > 0 else -1) if row_diff != 0 else 0
        c_step = (1 if col_diff > 0 else -1) if col_diff != 0 else 0
        r, c = sr + r_step, sc + c_step
        files = 'ABCDEFGH'
        while (r, c) != (dr, dc):
            sq = f"{files[c]}{r+1}"
            if board.get(sq):
                return False, f"Path blocked at {sq}"
            r += r_step
            c += c_step
        return True, ""

    elif kind == "BISHOP":
        if abs(row_diff) != abs(col_diff):
            return False, "Bishop must move diagonally"
        r_step = 1 if row_diff > 0 else -1
        c_step = 1 if col_diff > 0 else -1
        r, c = sr + r_step, sc + c_step
        files = 'ABCDEFGH'
        while (r, c) != (dr, dc):
            sq = f"{files[c]}{r+1}"
            if board.get(sq):
                return False, f"Path blocked at {sq}"
            r += r_step
            c += c_step
        return True, ""

    elif kind == "QUEEN":
        straight = row_diff == 0 or col_diff == 0
        diagonal = abs(row_diff) == abs(col_diff)
        if not (straight or diagonal):
            return False, "Queen must move straight or diagonally"
        # Reuse rook/bishop path logic
        r_step = (0 if row_diff == 0 else (1 if row_diff > 0 else -1))
        c_step = (0 if col_diff == 0 else (1 if col_diff > 0 else -1))
        r, c = sr + r_step, sc + c_step
        files = 'ABCDEFGH'
        while (r, c) != (dr, dc):
            sq = f"{files[c]}{r+1}"
            if board.get(sq):
                return False, f"Path blocked at {sq}"
            r += r_step
            c += c_step
        return True, ""

    elif kind == "KNIGHT":
        if sorted([abs(row_diff), abs(col_diff)]) != [1, 2]:
            return False, "Knight must move in an L-shape"
        return True, ""

    elif kind == "KING":
        if move_type == "CASTLE":
            return True, ""  # Simplified: trust caller flagged it correctly
        if abs(row_diff) <= 1 and abs(col_diff) <= 1 and (row_diff, col_diff) != (0, 0):
            return True, ""
        return False, "King can only move one square"

    return False, f"Unknown piece type: {kind}"


def apply_move(board: dict, src: str, dst: str, piece: str, move_type: str):
    """Return a new board dict with the move applied."""
    new_board = dict(board)
    new_board[dst] = piece
    del new_board[src]

    # En passant: remove the captured pawn
    if move_type == "EN_PASSANT":
        captured_row = str(int(dst[1]) + (-1 if piece.startswith("WHITE") else 1))
        new_board.pop(f"{dst[0]}{captured_row}", None)

    return new_board


def king_in_check(board: dict, color: str):
    """Return True if 'color' king is under attack."""
    king_sq = next((sq for sq, p in board.items() if p == f"{color}_KING"), None)
    if not king_sq:
        return False
    opponent = "BLACK" if color == "WHITE" else "WHITE"
    for sq, piece in board.items():
        if piece.startswith(opponent):
            ok, _ = validate_move(piece, sq, king_sq, board, "NORMAL")
            if ok:
                return True
    return False


# ── gRPC service implementation ────────────────────────────────────────────────

class MoveValidatorServicer(chess_pb2_grpc.MoveValidatorServicer):

    def ValidateMove(self, request, context):
        log.info(f"Request  game={request.game_id} player={request.player_id} "
                 f"{request.piece_position}→{request.target_position} ({request.move_type})")

        # Decode board state
        try:
            board = json.loads(request.board_state) if request.board_state else default_board()
        except json.JSONDecodeError:
            board = default_board()

        src = request.piece_position.upper()
        dst = request.target_position.upper()
        piece = board.get(src)

        # Run validation
        is_valid, error = validate_move(piece, src, dst, board, request.move_type)

        updated_board = board
        check_state = False
        checkmate = False

        if is_valid:
            updated_board = apply_move(board, src, dst, piece, request.move_type)
            opponent = "BLACK" if piece.startswith("WHITE") else "WHITE"
            check_state = king_in_check(updated_board, opponent)

            # Self-check: illegal if your own king ends up in check
            mover_color = piece.split("_")[0]
            if king_in_check(updated_board, mover_color):
                is_valid = False
                error = "Move leaves your king in check"
                updated_board = board

        result = chess_pb2.ValidateMoveResponse(
            is_valid=is_valid,
            move_type=request.move_type,
            check_state=check_state,
            checkmate=checkmate,
            updated_board=json.dumps(updated_board),
            error_message=error,
        )

        log.info(f"Response valid={is_valid} check={check_state} error='{error}'")
        return result


# ── Entry point ────────────────────────────────────────────────────────────────

def serve():
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    chess_pb2_grpc.add_MoveValidatorServicer_to_server(MoveValidatorServicer(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    log.info("Microservice listening on port 50051  (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        server.stop(0)

if __name__ == "__main__":
    serve()
