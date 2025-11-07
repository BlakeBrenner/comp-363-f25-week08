G = [
    [0, 1, 1, 0, 0, 0],
    [0, 0, 0, 1, 1, 0],
    [0, 1, 0, 0, 1, 0],
    [0, 0, 0, 0, 1, 1],
    [0, 0, 0, 0, 0, 1],
    [0, 0, 0, 0, 0, 0]
]

def compute_in_degrees(graph: list[list[int]]) -> list[int]:
    #shortcut to the num of verticies for easy ref
    n = len(graph)
    in_deg = [-1]*n
    for vertex in range(n):
        count = 0
        for neighbor in range(n):
            if G[neighbor][vertex] != 0:
                count += 1
        in_deg[vertex] = count
    return in_deg

#should return list of vertex in order of topological 
def topo_sort(graph: list[list[int]]) -> list[int]:
    """returns a list of vertex labels in topological order"""
    n = len(graph)
    topo = []
    #compute the in-degrees for every vertex in the graph
    in_degrees: list[int] =  compute_in_degrees(graph)
    #initalize bag of source verticies
    source = []
    for u in range(n):
        if in_degrees[u] == 0:
            #vertex is a source vertex
            source.append(u)
    while len(source) > 0:
        #while there are source verticies in the bag
        #grab one
        u = source.pop()
        #find all neighbors of u and reduce their in-degree
        for neighbor in range(n):
            if graph[u][neighbor] != 0:
                in_degrees[neighbor] -= 1
                if in_degrees[neighbor] == 0:
                    #if nieghbor becomes source add it to source
                    source.append(neighbor)
        topo.append(u)
    return topo
print(compute_in_degrees(G))
print(topo_sort(G))