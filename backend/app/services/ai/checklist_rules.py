"""
Официальные правила чек-листа CQA Freedom Broker и расчёт баллов.
Основано на регламенте из PDF:
- Динамическая поддержка любого переданного чек-листа (по умолчанию официальные 8 критериев)
- Перераспределение весов при N/A: Итог = (Сумма баллов / Сумма весов применимых) * 100
- Шкальные критерии: (балл / макс_шкалы) * вес
- Строгая валидация структуры, допустимых значений, типов и существования реплик
"""

from typing import Dict, Any, List, Tuple, Optional


OFFICIAL_CHECKLIST = {
    "01": {
        "id": "01",
        "name": "Установление контакта",
        "weight": 10,
        "type": "binary",
        "allowed_values": ["Да", "Нет"],
        "allows_na": False,
        "description": "Да — оператор поздоровался на языке клиента и представился в первом ответе."
    },
    "02": {
        "id": "02",
        "name": "Выявление потребности",
        "weight": 15,
        "type": "binary_na",
        "allowed_values": ["Да", "Нет", "N/A"],
        "allows_na": True,
        "description": "Да — оператор учёл известные детали и уточнил недостающее до ответа. N/A — данных для ответа хватало с самого начала."
    },
    "03": {
        "id": "03",
        "name": "Идентификация",
        "weight": 20,
        "type": "binary_na",
        "allowed_values": ["Да", "Нет", "N/A"],
        "allows_na": True,
        "description": "Да — проверка личности подтверждена до раскрытия данных или защищённого действия. N/A — запрос не требовал идентификации."
    },
    "04": {
        "id": "04",
        "name": "Корректная и полная консультация",
        "weight": 20,
        "type": "scale_na",
        "scale": [0, 5, 10, 15, 20],
        "scale_max": 20,
        "allowed_values": [0, 5, 10, 15, 20, "N/A"],
        "allows_na": True,
        "description": "Оцените ответ или следующий шаг по шкале 0-20. N/A — чат закончился до того, как клиент сформулировал запрос."
    },
    "05": {
        "id": "05",
        "name": "Эмпатия и клиентоориентированность",
        "weight": 15,
        "type": "binary",
        "allowed_values": ["Да", "Нет"],
        "allows_na": False,
        "description": "Да — оператор вежлив и, если клиент выразил недовольство или описал неудобство, отреагировал на конкретную проблему."
    },
    "06": {
        "id": "06",
        "name": "Управление диалогом, скорость и грамотность",
        "weight": 15,
        "type": "scale",
        "scale": [0, 4, 7, 10],
        "scale_max": 10,
        "allowed_values": [0, 4, 7, 10],
        "allows_na": False,
        "description": "Оцените ясность, порядок ответов и предупреждение об ожидании по шкале 0-10."
    },
    "07": {
        "id": "07",
        "name": "Завершение",
        "weight": 5,
        "type": "binary_na",
        "allowed_values": ["Да", "Нет", "N/A"],
        "allows_na": True,
        "description": "Да — оператор подвёл итог или предложил дальнейшую помощь и попрощался. N/A — чат оборвался до возможности его завершить."
    },
    "08": {
        "id": "08",
        "name": "Грубые ошибки",
        "weight": 0,
        "type": "flag",
        "allowed_values": ["Да", "Нет"],
        "allows_na": False,
        "description": "Да — выявлено оскорбление, предложение услуги в обход компании или раскрытие конфиденциальной инфы. Нет — нарушений нет."
    }
}

# Обратная совместимость со старым именем переменной
CHECKLIST_CRITERIA = OFFICIAL_CHECKLIST


def normalize_value(raw_val: Any) -> Any:
    """Нормализует строковые и числовые значения для сравнения."""
    if raw_val is None:
        return "N/A"
    s = str(raw_val).strip()
    if s.upper() in ["NA", "N/A", "НЕПРИМЕНИМО"]:
        return "N/A"
    if s.capitalize() in ["Да", "Yes", "Иә", "Иа"]:
        return "Да"
    if s.capitalize() in ["Нет", "No", "Жоқ", "Жок"]:
        return "Нет"
    try:
        num = int(s)
        return num
    except ValueError:
        return s


def calculate_score(
    evaluations: Dict[str, Dict[str, Any]],
    checklist: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Рассчитывает баллы по официальной формуле хакатона Freedom Broker.
    Поддерживает динамический чек-лист любой конфигурации.

    1. «Да» даёт полный вес, «Нет» — ноль.
    2. Шкальные оценки пересчитываются пропорционально: (ступень / scale_max) * вес.
    3. N/A исключаются, веса пропорционально перераспределяются:
       Итог = (сумма_баллов / сумма_весов_применимых) * 100
    4. Округление до 2 знаков в финале. Промежуточные расчёты сохраняют полную точность.
    5. Грубая ошибка отмечается отдельно и НЕ обнуляет числовой итог автоматически.
    """
    cl = checklist or OFFICIAL_CHECKLIST
    applicable_weight_sum = 0.0
    earned_points_sum = 0.0
    breakdown = {}
    gross_error = False

    for cid, rule in cl.items():
        weight = float(rule.get("weight", 0))
        crit_eval = evaluations.get(cid, {})
        val = normalize_value(crit_eval.get("value"))

        explanation = crit_eval.get("explanation", "")
        evidence_replicas = crit_eval.get("evidence_replicas", [])

        earned_points = 0.0
        is_na = (val == "N/A")
        rule_type = rule.get("type", "binary")

        if rule_type == "flag":
            gross_error = (val == "Да")
            earned_points = 0.0
        elif is_na:
            earned_points = 0.0
        else:
            applicable_weight_sum += weight
            if rule_type in ["binary", "binary_na"]:
                if val == "Да":
                    earned_points = weight
                else:
                    earned_points = 0.0
            elif rule_type in ["scale", "scale_na"]:
                try:
                    num_val = float(val)
                    scale_max = float(rule.get("scale_max", 10))
                    earned_points = (num_val / scale_max) * weight
                except (ValueError, TypeError):
                    earned_points = 0.0

            earned_points_sum += earned_points

        breakdown[cid] = {
            "name": rule.get("name", f"Критерий {cid}"),
            "weight": weight,
            "raw_value": val,
            "is_na": is_na,
            "earned_points": round(earned_points, 4),
            "explanation": explanation,
            "evidence_replicas": evidence_replicas
        }

    if applicable_weight_sum > 0:
        total_score = round((earned_points_sum / applicable_weight_sum) * 100.0, 2)
    else:
        total_score = None

    return {
        "total_score": total_score,
        "applicable_weight_sum": round(applicable_weight_sum, 2),
        "earned_points_sum": round(earned_points_sum, 4),
        "gross_error": gross_error,
        "criteria": breakdown
    }



def validate_evaluation(
    eval_dict: Dict[str, Any],
    transcript: List[Dict[str, Any]],
    checklist: Optional[Dict[str, Any]] = None
) -> Tuple[bool, List[str]]:

    errors = []
    cl = checklist or OFFICIAL_CHECKLIST
    total_replicas = len(transcript)

    if not isinstance(eval_dict, dict):
        return False, ["Ответ модели не является JSON-объектом"]

    # Check unknown criteria
    for key in eval_dict.keys():
        if key not in cl:
            errors.append(
                f"Обнаружен неизвестный критерий '{key}'"
            )

    # Check every expected criterion
    for cid, rule in cl.items():

        if cid not in eval_dict:
            errors.append(
                f"Критерий {cid} ({rule.get('name')}) отсутствует"
            )
            continue

        c_data = eval_dict[cid]

        if not isinstance(c_data, dict):
            errors.append(
                f"Критерий {cid}: данные должны быть объектом"
            )
            continue

        val = normalize_value(c_data.get("value"))
        allowed = rule.get("allowed_values", [])
        allows_na = rule.get("allows_na", False)

        # Convert numeric strings to allowed numeric values
        if isinstance(val, str) and val != "N/A":
            try:
                numeric_val = float(val)

                for allowed_value in allowed:
                    if (
                        isinstance(allowed_value, (int, float))
                        and not isinstance(allowed_value, bool)
                        and numeric_val == float(allowed_value)
                    ):
                        val = allowed_value
                        break

            except (ValueError, TypeError):
                pass

        # Check N/A permission
        if val == "N/A" and not allows_na:
            errors.append(
                f"Критерий {cid}: N/A запрещено"
            )

        # Numeric scales can come from the UI as floats and from the model as
        # integers. Compare their numeric values without treating booleans as numbers.
        is_allowed = any(
            ((type(val) in (int, float) and type(item) in (int, float))
             or type(val) == type(item)) and val == item
            for item in allowed
        )

        if not is_allowed:
            errors.append(
                f"Критерий {cid} ({rule.get('name')}): "
                f"недопустимое значение '{val}'. Разрешено: {allowed}"
            )

        # Check explanation
        explanation = c_data.get("explanation")

        if not explanation or not str(explanation).strip():
            errors.append(
                f"Критерий {cid}: explanation пустое"
            )

        # Check evidence replicas
        evidence = c_data.get("evidence_replicas")

        if evidence is None or not isinstance(evidence, list):
            errors.append(
                f"Критерий {cid}: evidence_replicas должен быть списком"
            )
        elif not evidence:
            errors.append(f"Критерий {cid}: evidence_replicas не должен быть пустым")
        else:
            for replica in evidence:

                if isinstance(replica, bool):
                    errors.append(
                        f"Критерий {cid}: некорректный номер реплики"
                    )
                    continue

                if isinstance(replica, int):
                    number = replica

                else:
                    errors.append(
                        f"Критерий {cid}: некорректный идентификатор "
                        f"реплики '{replica}'"
                    )
                    continue

                if not (1 <= number <= total_replicas):
                    errors.append(
                        f"Критерий {cid}: реплика #{number} "
                        f"не существует (всего: {total_replicas})"
                    )

    return len(errors) == 0, errors
