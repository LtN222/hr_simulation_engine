def allocate_headcount(structure: dict, total_employees: int):

    role_allocations = []

    for afdeling, functies in structure.items():
        for functie, details in functies.items():

            exact = total_employees * details["fte_ratio"]
            floor_count = int(exact)
            remainder = exact - floor_count

            role_allocations.append({
                "Department_Name": afdeling,
                "Role_Name": functie,
                "count": floor_count,
                "remainder": remainder
            })

    current_total = sum(r["count"] for r in role_allocations)
    remaining = total_employees - current_total

    role_allocations.sort(key=lambda x: x["remainder"], reverse=True)

    i = 0
    while remaining > 0:
        role_allocations[i]["count"] += 1
        remaining -= 1
        i = (i + 1) % len(role_allocations)

    return role_allocations