def generate_employment_attributes(
    employment_key,
    role_row,
    employment_attributes_config,
    rng
):

    attributes = []

    for attr_name, attr_config in employment_attributes_config.items():

        applies = True

        if "applies_if" in attr_config:
            applies = bool(role_row[attr_config["applies_if"]])

        if applies:

            value = rng.choices(
                attr_config["values"],
                weights=attr_config.get("weights")
            )[0]

            attributes.append({

                "Employment_Key": employment_key,
                "Attribute_Name": attr_name,
                "Attribute_Value": value

            })

    return attributes