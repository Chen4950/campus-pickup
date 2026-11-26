from collections import defaultdict
from heapq import heappop, heappush

MAX_STOPS = 8


class StationRoutes:
    def __init__(self, station, layout):
        self.station = station
        self.shelves = {node["id"] for node in layout["nodes"] if node["type"] == "shelf"}
        self.edges = {
            (edge["from"], edge["to"]): edge["distance_m"]
            for edge in layout["directed_edges"]
        }

    def plan(self, start, requested, closed=()):
        entry = self.station["entry_node"]
        verify = self.station["verification_node"]
        exit_node = self.station["exit_node"]
        if start not in self.shelves | {entry}:
            raise ValueError("请选择入口或当前所在的货架。")
        stops = list(dict.fromkeys(requested))
        if len(stops) > MAX_STOPS:
            raise ValueError(f"一次最多规划 {MAX_STOPS} 个不同取件点。")
        if unknown := sorted(set(stops) - self.shelves):
            raise ValueError(f"找不到货架：{'、'.join(unknown)}。")
        closed = set(closed)
        if closed.difference(self.edges):
            raise ValueError("封闭通道包含未登记的路线。")
        graph = defaultdict(list)
        for (source, target), distance in self.edges.items():
            if (source, target) not in closed:
                graph[source].append((target, distance))

        exit_path = self._search(graph, verify, exit_node, [])
        if exit_path is None or self._search(graph, start, verify, []) is None:
            raise ValueError("当前位置无法经核验点到达出口，请联系驿站工作人员。")
        unreachable = [
            shelf for shelf in stops
            if self._search(graph, start, verify, [shelf]) is None
        ]
        reachable = [shelf for shelf in stops if shelf not in unreachable]
        best = self._search(graph, start, verify, reachable)
        if best is None:
            raise ValueError("这些货架无法在同一条单向路线内全部取完，请减少本次取件点。")
        baseline = self._search(graph, start, verify, reachable, ordered=True)
        steps = list(dict.fromkeys(node for node in best[1] if node in reachable))
        distance = best[0] + exit_path[0]
        baseline_distance = baseline[0] + exit_path[0] if baseline else None
        return {
            "stops": steps,
            "path": best[1] + exit_path[1][1:],
            "distance_m": distance,
            "to_verification_m": best[0],
            "baseline_distance_m": baseline_distance,
            "saved_m": baseline_distance - distance if baseline_distance is not None else None,
            "unreachable_shelves": unreachable,
        }

    def _search(self, graph, source, target, stops, ordered=False):
        # The search state includes the shelves already visited, so a shelf is
        # picked in the order it is actually passed along the returned path.
        stop_bits = {shelf: 1 << index for index, shelf in enumerate(stops)}
        complete = len(stops) if ordered else (1 << len(stops)) - 1

        def visit(node, progress):
            if ordered:
                return progress + (progress < complete and node == stops[progress])
            return progress | stop_bits.get(node, 0)

        starting_state = (source, visit(source, 0))
        pending = [(0, starting_state)]
        distance = {starting_state: 0}
        previous = {}
        gate = self.station["verification_node"]
        exit_node = self.station["exit_node"]
        while pending:
            length, state = heappop(pending)
            if length != distance[state]:
                continue
            node, progress = state
            if node == target and progress == complete:
                path = [node]
                while state in previous:
                    state = previous[state]
                    path.append(state[0])
                return length, list(reversed(path))
            for neighbor, weight in graph[node]:
                if target == gate and (neighbor == exit_node or (neighbor == gate and progress != complete)):
                    continue
                next_state = (neighbor, visit(neighbor, progress))
                new_distance = length + weight
                if new_distance < distance.get(next_state, float("inf")):
                    distance[next_state] = new_distance
                    previous[next_state] = state
                    heappush(pending, (new_distance, next_state))
        return None
