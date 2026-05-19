"""
Chess Validator — Test Client
CS 361 - Microservice A

COMMUNICATION PIPE: gRPC over TCP port 50051
─────────────────────────────────────────────────────────────
This file and server.py do NOT import each other.
They communicate exclusively through the gRPC network pipe:

  test_client.py  ──[gRPC request]──►  server.py
  test_client.py  ◄─[gRPC response]──  server.py

Requesting data:  stub.ValidateMove(ValidateMoveRequest(...))
Receiving data:   response.is_valid, response.error_message, etc.
─────────────────────────────────────────────────────────────

Run AFTER starting server.py in a separate terminal:
    python3 server.py          # terminal 1
    python3 test_client.py     # terminal 2
"""

import grpc
import json

import chess_pb2
import chess_pb2_grpc

SERVER_ADDRESS = "localhost:50051"

# Starting board used for all tests
STARTING_BOARD = {
    "A1":"WHITE_ROOK",  "B1":"WHITE_KNIGHT","C1":"WHITE_BISHOP",
    "D1":"WHITE_QUEEN", "E1":"WHITE_KING",  "F1":"WHITE_BISHOP",
    "G1":"WHITE_KNIGHT","H1":"WHITE_ROOK",
    "A2":"WHITE_PAWN",  "B2":"WHITE_PAWN",  "C2":"WHITE_PAWN",
    "D2":"WHITE_PAWN",  "E2":"WHITE_PAWN",  "F2":"WHITE_PAWN",
    "G2":"WHITE_PAWN",  "H2":"WHITE_PAWN",
    "A7":"BLACK_PAWN",  "B7":"BLACK_PAWN",  "C7":"BLACK_PAWN",
    "D7":"BLACK_PAWN",  "E7":"BLACK_PAWN",  "F7":"BLACK_PAWN",
    "G7":"BLACK_PAWN",  "H7":"BLACK_PAWN",
    "A8":"BLACK_ROOK",  "B8":"BLACK_KNIGHT","C8":"BLACK_BISHOP",
    "D8":"BLACK_QUEEN", "E8":"BLACK_KING",  "F8":"BLACK_BISHOP",
    "G8":"BLACK_KNIGHT","H8":"BLACK_ROOK",
}

# ── Test cases ─────────────────────────────────────────────────────────────────
# Each entry: (description, piece_pos, target_pos, move_type, expect_valid)
TEST_CASES = [
    ("Pawn advances two squares from start",            "E2", "E4", "NORMAL", True),
    ("Pawn advances one square",                        "D2", "D3", "NORMAL", True),
    ("Pawn tries to move three squares",                "A2", "A5", "NORMAL", False),
    ("Pawn tries to move sideways",                     "B2", "C2", "NORMAL", False),
    ("Knight jumps to valid square",                    "G1", "F3", "NORMAL", True),
    ("Knight tries an illegal move",                    "B1", "B3", "NORMAL", False),
    ("Bishop blocked by own pawn",                      "C1", "E3", "NORMAL", False),
    ("King tries to move two squares (no castle flag)", "E1", "G1", "NORMAL", False),
    ("Move from an empty square",                       "E5", "E6", "NORMAL", False),
    ("Pawn tries to move backward",                     "E2", "E1", "NORMAL", False),
]


def run_tests():
    # Connect to the microservice over gRPC — server.py is NOT imported here
    channel = grpc.insecure_channel(SERVER_ADDRESS)
    stub = chess_pb2_grpc.MoveValidatorStub(channel)
    board_json = json.dumps(STARTING_BOARD)

    print("=" * 60)
    print("  Chess Move Validation - Microservice Test Suite")
    print("=" * 60)

    passed = 0
    failed = 0

    for i, (desc, src, dst, move_type, expect_valid) in enumerate(TEST_CASES, 1):

        # ── REQUEST ──────────────────────────────────────────────────────────
        # Build the request object and send it to the microservice over the
        # gRPC pipe. server.py receives this — it is NOT called directly.
        request = chess_pb2.ValidateMoveRequest(
            game_id         = "test_game_001",
            player_id       = "tester",
            piece_position  = src,
            target_position = dst,
            move_type       = move_type,
            board_state     = board_json,
        )

        try:
            # This line sends the request over the gRPC pipe and blocks
            # until the microservice (server.py) sends back a response.
            response = stub.ValidateMove(request)

            # ── RECEIVE ──────────────────────────────────────────────────────
            # server.py processed the move and returned a ValidateMoveResponse.
            # Read each field directly off the response object — no parsing needed.
            got_valid  = response.is_valid        # bool   — was the move legal?
            detail     = response.error_message if not got_valid else "Move accepted"
            check_note = "  ♚ Check!" if response.check_state else ""
            # Also available:
            #   response.updated_board  — JSON board state after the move
            #   response.checkmate      — True if opponent has no moves left
            #   response.move_type      — echoes the move_type we sent

            status = "PASS" if got_valid == expect_valid else "FAIL"
            passed += 1 if status == "PASS" else 0
            failed += 1 if status == "FAIL" else 0

            print(f"\n[{i:02d}] {status}  {src}->{dst}  ({move_type})")
            print(f"      {desc}")
            print(f"      Expected valid={expect_valid}  Got valid={got_valid}")
            print(f"      Microservice says: {detail}{check_note}")

        except grpc.RpcError as e:
            print(f"\n[{i:02d}] ERROR - could not reach server: {e.code()}")
            print("       Make sure server.py is running on port 50051.")
            failed += 1

    print("\n" + "=" * 60)
    print(f"  Results: {passed} passed / {failed} failed / {len(TEST_CASES)} total")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
