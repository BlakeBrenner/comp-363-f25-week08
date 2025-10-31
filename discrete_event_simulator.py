from dataclasses import dataclass
import random
from collections import deque

# ------------------------
# Global configuration
# ------------------------

# Size of grid
N = 4
# Length of simulation in time ticks
TOTAL_TICKS = 1_000

# Cardinal direction constants
NORTH = "N"
SOUTH = "S"
EAST = "E"
WEST = "W"

# Directions in clockwise order for easy turning using modular arithmetic
CLOCKWISE = [NORTH, EAST, SOUTH, WEST]

# Turn constants
STRAIGHT = "straight"
LEFT = "left"
RIGHT = "right"

# Turn probabilities [left, straight, right]
TURN_PROBABILITIES = [0.25, 0.50, 0.25]

# Traffic light timing
CYCLE_NS_GREEN = 20
CYCLE_EW_GREEN = 20
CYCLE_TOTAL = CYCLE_NS_GREEN + CYCLE_EW_GREEN

# How many cars can flow through a green light per time tick?
FLOW_PER_TICK = 1

# Link capacity: how many cars in transit are allowed between neighboring nodes
LINK_IN_TRANSIT_CAP = 50

# How many cars can wait at a stop light
QUEUE_CAP = 10

# Travel timing (base deterministic travel time for one link)
BASE_TRAVEL_T = 6

# Arrival rate: probability of a car arriving per boundary approach per tick
ARRIVAL_RATE = 0.33


# ------------------------
# Data classes
# ------------------------

@dataclass(frozen=True)
class Node:
    i: int  # index of E-W street (row)
    j: int  # index of N-S street (col)


@dataclass
class Car:
    id: int        # unique identifier for the car
    t_enter: int   # time step when the car enters the grid


# ------------------------
# Mesoscopic helpers
# ------------------------

def outgoing_for(node: Node) -> list[tuple[Node, str]]:
    """
    Return list of (dst_node, direction) tuples for outgoing links from node.
    """
    directions = []
    i, j = node.i, node.j
    if i > 0:
        directions.append((Node(i - 1, j), NORTH))
    if j < N - 1:
        directions.append((Node(i, j + 1), EAST))
    if i < N - 1:
        directions.append((Node(i + 1, j), SOUTH))
    if j > 0:
        directions.append((Node(i, j - 1), WEST))
    return directions


def incoming_for(node: Node) -> list[tuple[Node, str]]:
    """
    Return list of (src_node, approach_direction) tuples for links entering node.
    approach_direction is the direction FROM WHICH the car arrives.
    """
    directions = []
    i, j = node.i, node.j
    if i < N - 1:
        # car comes from below, so it's approaching from SOUTH going NORTH
        directions.append((Node(i + 1, j), NORTH))
    if j > 0:
        # car comes from left, so it's approaching from WEST going EAST
        directions.append((Node(i, j - 1), EAST))
    if i > 0:
        # car comes from above, so it's approaching from NORTH going SOUTH
        directions.append((Node(i - 1, j), SOUTH))
    if j < N - 1:
        # car comes from right, so it's approaching from EAST going WEST
        directions.append((Node(i, j + 1), WEST))
    return directions


def turn_direction(approach_direction: str) -> str:
    """
    Given the approach direction (where the car is coming from),
    randomly pick LEFT / STRAIGHT / RIGHT using TURN_PROBABILITIES,
    and return the new travel direction.
    """
    left, straight, right = TURN_PROBABILITIES
    rand = random.random()

    if rand < left:
        turn = LEFT
    elif rand < left + straight:  # teacher correction here
        turn = STRAIGHT
    else:
        turn = RIGHT

    # default is straight (keep same direction)
    new_direction = approach_direction

    if turn != STRAIGHT:
        # find index of the approach direction in clockwise order
        approach_idx = CLOCKWISE.index(approach_direction)  # teacher correction here
        # left turn = counter-clockwise (-1), right turn = clockwise (+1)
        delta = -1 if turn == LEFT else 1
        new_idx = (approach_idx + delta) % len(CLOCKWISE)
        new_direction = CLOCKWISE[new_idx]

    return new_direction


def is_boundary_incoming_link(src: Node, dst: Node) -> bool:
    """
    True if link src->dst represents a car entering the grid from 'outside'.

    src is on the boundary and dst is the first node one step further in.
    """
    si, sj = src.i, src.j
    di, dj = dst.i, dst.j

    return (
        (si == 0 and di == si + 1 and sj == dj)               # entering southbound from north edge
        or (si == N - 1 and di == si - 1 and sj == dj)         # entering northbound from south edge
        or (sj == 0 and dj == sj + 1 and si == di)             # entering eastbound from west edge
        or (sj == N - 1 and dj == sj - 1 and si == di)         # entering westbound from east edge
    )


def signal_phase(t: int, node: Node) -> list[str]:
    """
    For this node at time t, which approach directions have green?
    We alternate NS vs EW based on the cycle timings.
    """
    tt = t % CYCLE_TOTAL

    # default assume east-west green
    green_axis = [EAST, WEST]

    # first CYCLE_NS_GREEN ticks are north-south green
    if tt < CYCLE_NS_GREEN:
        green_axis = [NORTH, SOUTH]

    return green_axis


def add_travel_time(base: int = BASE_TRAVEL_T) -> int:
    """
    Travel time for one link.
    Placeholder where you'd add noise/jitter if desired.
    """
    return base


# ------------------------
# Network state (links, queues)
# ------------------------

# in_transit[(u,v)] = deque of (Car, remaining_time_on_link)
in_transit: dict[tuple[Node, Node], deque] = {}

# stopped[(u,v)] = deque of Cars waiting at the downstream red light for link u->v
stopped: dict[tuple[Node, Node], deque] = {}

# Make the grid of nodes
nodes = [Node(i, j) for i in range(N) for j in range(N)]

# Build the directed links and initialize data structures
links = []
for u in nodes:
    for v, _direction in outgoing_for(u):
        links.append((u, v))
        in_transit[(u, v)] = deque()
        stopped[(u, v)] = deque()


# ------------------------
# Primitive link/light operations
# ------------------------

def enqueue_departure(src: Node, dst: Node, car: Car) -> bool:
    """
    Try to put 'car' on link src->dst if there's capacity.
    Returns True if successful.
    """
    buf = in_transit[(src, dst)]
    if len(buf) < LINK_IN_TRANSIT_CAP:
        buf.append((car, add_travel_time()))
        return True
    return False


def pop_to_queue_if_arrived(src: Node, dst: Node) -> int:
    """
    Decrease remaining travel time for each car on link src->dst.
    When a car reaches time <= 0, try to move it into the downstream
    stoplight queue (stopped[(src,dst)]). If the queue is full,
    keep the car at the head of the link with remaining_time 0.
    Returns number of cars that successfully moved.
    """
    buf = in_transit[(src, dst)]

    # age all cars by 1 tick
    for k in range(len(buf)):
        car, remaining = buf[k]
        buf[k] = (car, remaining - 1)

    moved = 0
    q = stopped[(src, dst)]
    tmp = deque()

    while buf:
        car, remaining = buf.popleft()

        if remaining <= 0:
            # car finished traversing the link, try to queue at light
            if len(q) < QUEUE_CAP:
                q.append(car)
                moved += 1
            else:
                # downstream queue is full; car waits at head of link
                tmp.appendleft((car, 0))
        else:
            # still in transit
            tmp.append((car, remaining))

    in_transit[(src, dst)] = tmp
    return moved


def serve_intersection(t: int, node: Node, completed_cb) -> int:
    """
    Let cars with a green light at this intersection either
    (a) exit the grid or
    (b) move onto the next link (if capacity allows).
    completed_cb(car, t) is called if the car leaves the grid.
    Returns the number of cars moved/served.
    """
    green_dirs = signal_phase(t, node)
    served = 0

    for src_node, approach_dir in incoming_for(node):
        # Only move cars from approaches that currently have green.
        if approach_dir not in green_dirs:
            continue

        link_key = (src_node, node)
        q = stopped[link_key]

        moves_attempted = 0
        stop_processing = False

        # Try up to FLOW_PER_TICK vehicles from this queue
        while moves_attempted < FLOW_PER_TICK and not stop_processing and q:
            car = q[0]

            # Pick the car's next direction after the intersection
            next_dir = turn_direction(approach_dir)

            i, j = node.i, node.j
            next_node = None
            car_exits = False

            # Figure out where that direction goes in the grid.
            if next_dir == NORTH and i > 0:
                next_node = Node(i - 1, j)
            elif next_dir == SOUTH and i < N - 1:
                next_node = Node(i + 1, j)
            elif next_dir == WEST and j > 0:
                next_node = Node(i, j - 1)
            elif next_dir == EAST and j < N - 1:
                next_node = Node(i, j + 1)
            else:
                # That turn would take you off the grid -> car leaves system
                car_exits = True

            if car_exits:
                q.popleft()
                completed_cb(car, t)
                served += 1
                moves_attempted += 1
            else:
                # Try to enqueue onto the next link. If blocked, we stop.
                if enqueue_departure(node, next_node, car):
                    q.popleft()
                    served += 1
                    moves_attempted += 1
                else:
                    # downstream link is full; can't move more cars from this approach
                    stop_processing = True

    return served


# ------------------------
# Global statistics
# ------------------------

car_id = 0          # incremental car ID counter
completed = 0       # number of cars that fully left the grid
sum_tt = 0          # total travel time of all completed cars
queue_samples = 0   # number of queue-snapshot samples collected
sum_queue = 0       # total queued cars across all queues over all samples


def record_completion(car: Car, t_now: int) -> None:
    """
    Called when a car exits the grid.
    Update total completed count and sum of time-in-system.
    """
    global completed, sum_tt
    completed += 1
    sum_tt += (t_now - car.t_enter)


# ------------------------
# Simulator loop
# ------------------------

def simulate(random_seed: int | None = 12345) -> dict[str, float]:
    """
    Run the discrete event simulator for TOTAL_TICKS time steps.
    Return summary stats.
    """
    global car_id, completed, sum_tt, queue_samples, sum_queue

    if random_seed is not None:
        random.seed(random_seed)

    # Reset global stats/state in case simulate() is called multiple times
    car_id = 0
    completed = 0
    sum_tt = 0
    queue_samples = 0
    sum_queue = 0

    # Main time loop
    for t in range(TOTAL_TICKS):

        # (1) Generate new arrivals at boundary links.
        # For every link u->v where u is on the outside edge feeding in,
        # spawn a new car with probability ARRIVAL_RATE.
        for (u, v) in links:
            if is_boundary_incoming_link(u, v):
                if random.random() < ARRIVAL_RATE:
                    car_id += 1
                    new_car = Car(id=car_id, t_enter=t)
                    enqueue_departure(u, v, new_car)

        # (2) Advance cars along every link by 1 tick and push arrivals
        #     into downstream stop-light queues.
        for (u, v) in links:
            pop_to_queue_if_arrived(u, v)

        # (3) For each intersection, serve whichever approaches have green.
        for node in nodes:
            serve_intersection(t, node, completed_cb=record_completion)

        # (4) Collect queue statistics for this tick.
        # We'll average the queues across all approaches over time.
        total_len = 0
        for q in stopped.values():
            total_len += len(q)
        sum_queue += total_len
        queue_samples += len(stopped)

    # After all ticks, compute summary statistics.
    avg_travel_time = (sum_tt / completed) if completed > 0 else 0.0
    avg_queue_len_per_light = (sum_queue / queue_samples) if queue_samples > 0 else 0.0

    return {
        "ticks": TOTAL_TICKS,
        "cars_completed": completed,
        "avg_travel_time": avg_travel_time,
        "avg_queue_len_per_light": avg_queue_len_per_light,
    }


# ------------------------
# Script entry point
# ------------------------

if __name__ == "__main__":
    stats = simulate()
    print("Simulation summary:")
    for k, v in stats.items():
        print(f"{k}: {v}")
