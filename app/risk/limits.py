def can_open_new_position(open_positions_count: int, max_concurrent_positions: int) -> bool:
    return open_positions_count < max_concurrent_positions
