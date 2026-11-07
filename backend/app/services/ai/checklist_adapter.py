
def convert_checklist_to_ai(checklist):
    """
    Converts SQLAlchemy checklist criteria
    into the format expected by the AI module.
    """

    ai_checklist = {}
    criterion_id_map = {}

    criteria = sorted(
        checklist.criteria,
        key=lambda item: item.id
    )

    for index, criterion in enumerate(criteria, start=1):
        ai_id = f"{index:02d}"

        answer_type = criterion.answer_type
        na_allowed = criterion.na_allowed
        scale = criterion.scale or []

        if criterion.name.strip().lower() == "gross violations":
            ai_type = "flag"
            allowed_values = ["Да", "Нет"]

        elif answer_type == "yes_no":
            ai_type = "binary"
            allowed_values = ["Да", "Нет"]

        elif answer_type == "yes_no_na":
            ai_type = "binary_na"
            allowed_values = ["Да", "Нет", "N/A"]

        elif answer_type == "numeric":
            ai_type = "scale_na" if na_allowed else "scale"

            if not scale:
                raise ValueError(
                    f"Criterion '{criterion.name}' has no scale"
                )

            allowed_values = list(scale)

            if na_allowed:
                allowed_values.append("N/A")

        else:
            raise ValueError(
                f"Unsupported answer type: {answer_type}"
            )

        rule = {
            "id": ai_id,
            "name": criterion.name,
            "weight": criterion.weight,
            "type": ai_type,
            "allowed_values": allowed_values,
            "allows_na": na_allowed,
            "description": criterion.description
        }

        if scale:
            rule["scale"] = scale
            rule["scale_max"] = max(scale)

        ai_checklist[ai_id] = rule

        # AI criterion ID -> SQLite criterion ID
        criterion_id_map[ai_id] = criterion.id

    return ai_checklist, criterion_id_map
