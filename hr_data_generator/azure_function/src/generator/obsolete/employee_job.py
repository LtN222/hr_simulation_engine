def choose_salary(role_row, rng):

    return rng.randint(
        role_row["Salaris_min"],
        role_row["Salaris_max"]
    )


def choose_performance(rng):

    score = round(rng.normalvariate(3.5, 0.5), 2)

    return max(1, min(5, score))