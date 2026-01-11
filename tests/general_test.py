import opensemantic.core
import opensemantic.core.v1


def test_opensemantic():

    # Create an instance of OswBaseModel
    model = opensemantic.core.Entity(
        label=[opensemantic.core.Label(text="Test Entity")],
    )

    # Check if the instance is created successfully
    assert isinstance(
        model, opensemantic.core.Entity
    ), "Failed to create an instance of Entity"

    # repeaet for v1
    model_v1 = opensemantic.core.v1.Entity(
        label=[opensemantic.core.v1.Label(text="Test Entity")],
    )
    assert isinstance(
        model_v1, opensemantic.core.v1.Entity
    ), "Failed to create an instance of Entity in v1"


if __name__ == "__main__":
    test_opensemantic()
    print("All tests passed!")
