
def calculate_score(criteria, answers):
    applicable_criteria = []
    gross_violation = False

    for criterion in criteria:
        criterion_id = str(criterion["id"])
        answer = answers.get(criterion_id)

        if answer is None:
            raise ValueError(
                f"Missing answer for {criterion['name']}"
            )

        # Gross violations are evaluated separately
        if criterion["name"] == "Gross Violations":
            if answer not in ["YES", "NO"]:
                raise ValueError(
                    "Gross Violations must be YES or NO"
                )

            gross_violation = answer == "YES"
            continue

        # Validate N/A
        if answer == "N/A":
            if not criterion["na_allowed"]:
                raise ValueError(
                    f"N/A is not allowed for {criterion['name']}"
                )
            continue

        applicable_criteria.append((criterion, answer))

    total_weight = sum(
        criterion["weight"]
        for criterion, answer in applicable_criteria
    )

    if total_weight == 0:
        return {
            "score": None,
            "gross_violation": gross_violation,
            "details": []
        }

    total_score = 0
    details = []

    for criterion, answer in applicable_criteria:
        weight = criterion["weight"]
        answer_type = criterion["answer_type"]

        if answer_type in ["yes_no", "yes_no_na"]:
            if answer not in ["YES", "NO"]:
                raise ValueError(
                    f"Invalid answer for {criterion['name']}"
                )

            raw_points = weight if answer == "YES" else 0

        elif answer_type == "numeric":
            scale = criterion.get("scale") or []

            if (
                isinstance(answer, bool)
                or not isinstance(answer, (int, float))
                or answer not in scale
            ):
                raise ValueError(
                    f"Invalid numeric answer for {criterion['name']}"
                )

            max_value = max(scale)

            if max_value <= 0:
                raise ValueError(
                    f"Invalid scale for {criterion['name']}"
                )

            raw_points = weight * answer / max_value

        else:
            raise ValueError(
                f"Unknown answer type: {answer_type}"
            )

        final_points = raw_points * 100 / total_weight
        total_score += final_points

        details.append({
            "criterion": criterion["name"],
            "answer": answer,
            "weight": weight,
            "points": round(final_points, 2)
        })

    return {
        "score": round(total_score, 2),
        "gross_violation": gross_violation,
        "details": details
    }
