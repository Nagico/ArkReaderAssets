import heapq


class PositionDispatcher:
    def __init__(self):
        self.counter = 0
        self.released_positions = []
        self.released_set = set()  # 用于快速检查位置是否已释放

    def request(self):
        if self.released_positions:
            # Get the smallest released position
            position = heapq.heappop(self.released_positions)
            self.released_set.remove(position)
        else:
            # Assign a new position
            position = self.counter
            self.counter += 1
        return position

    def release(self, position):
        if position < self.counter and position not in self.released_set:
            heapq.heappush(self.released_positions, position)
            self.released_set.add(position)
        else:
            raise ValueError("Invalid or already released position")