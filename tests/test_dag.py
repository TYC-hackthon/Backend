import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import BranchInfo, MessageNode, User
from app.services.message_nodes import (
    calculate_branch_diff,
    find_ancestor_path,
    nodes_to_messages,
    rebuild_context_nodes,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_linear_rebuild_context_nodes(db_session):
    user = User(id=1, username="testuser", password_hash="hash", is_admin=False, is_active=True)
    db_session.add(user)
    db_session.commit()

    n1 = MessageNode(id=1, user_id=1, parent_id=None, role="user", content="Hello")
    n2 = MessageNode(id=2, user_id=1, parent_id=1, role="assistant", content="Hi there")
    n3 = MessageNode(
        id=3,
        user_id=1,
        parent_id=2,
        role="exchange",
        content="How are you?",
        user_content="How are you?",
        assistant_content="I am fine",
    )
    db_session.add_all([n1, n2, n3])
    db_session.commit()

    nodes = rebuild_context_nodes(db_session, 3, user_id=1)
    assert [n.id for n in nodes] == [1, 2, 3]

    messages = nodes_to_messages(nodes)
    assert len(messages) == 4
    assert messages[0] == {"role": "user", "content": "Hello"}
    assert messages[1] == {"role": "assistant", "content": "Hi there"}
    assert messages[2] == {"role": "user", "content": "How are you?"}
    assert messages[3] == {"role": "assistant", "content": "I am fine"}


def test_branching_and_diff(db_session):
    user = User(id=1, username="testuser", password_hash="hash", is_admin=False, is_active=True)
    db_session.add(user)
    db_session.commit()

    # Tree:
    # 1 (root) -> 2 -> 3 (Branch A)
    #               -> 4 -> 5 (Branch B)
    n1 = MessageNode(id=1, user_id=1, parent_id=None, role="user", content="Root question")
    n2 = MessageNode(id=2, user_id=1, parent_id=1, role="assistant", content="Root answer")
    n3 = MessageNode(
        id=3,
        user_id=1,
        parent_id=2,
        role="exchange",
        content="Branch A question",
        user_content="Branch A question",
        assistant_content="Branch A answer",
    )
    n4 = MessageNode(
        id=4,
        user_id=1,
        parent_id=2,
        role="exchange",
        content="Branch B question",
        user_content="Branch B question",
        assistant_content="Branch B answer",
    )
    n5 = MessageNode(
        id=5,
        user_id=1,
        parent_id=4,
        role="exchange",
        content="Branch B follow-up",
        user_content="Branch B follow-up",
        assistant_content="Branch B follow-up answer",
    )
    db_session.add_all([n1, n2, n3, n4, n5])
    db_session.commit()

    # Context of branch A
    nodes_a = rebuild_context_nodes(db_session, 3, user_id=1)
    assert [n.id for n in nodes_a] == [1, 2, 3]

    # Context of branch B
    nodes_b = rebuild_context_nodes(db_session, 5, user_id=1)
    assert [n.id for n in nodes_b] == [1, 2, 4, 5]

    # Diff between Branch A and Branch B
    diff = calculate_branch_diff(db_session, 3, 5, user_id=1)
    assert diff["lca_node"] is not None
    assert diff["lca_node"]["id"] == 2
    assert [n["id"] for n in diff["branch_a_nodes"]] == [3]
    assert [n["id"] for n in diff["branch_b_nodes"]] == [4, 5]


def test_cycle_detection(db_session):
    user = User(id=1, username="testuser", password_hash="hash", is_admin=False, is_active=True)
    db_session.add(user)
    db_session.commit()

    n1 = MessageNode(id=1, user_id=1, parent_id=2, role="user", content="Cycle 1")
    n2 = MessageNode(id=2, user_id=1, parent_id=1, role="assistant", content="Cycle 2")
    db_session.add_all([n1, n2])
    db_session.commit()

    with pytest.raises(RuntimeError, match="cycle detected"):
        rebuild_context_nodes(db_session, 2, user_id=1)


def test_user_isolation(db_session):
    u1 = User(id=1, username="user1", password_hash="hash", is_admin=False, is_active=True)
    u2 = User(id=2, username="user2", password_hash="hash", is_admin=False, is_active=True)
    db_session.add_all([u1, u2])
    db_session.commit()

    n1 = MessageNode(id=1, user_id=1, parent_id=None, role="user", content="Secret")
    db_session.add(n1)
    db_session.commit()

    with pytest.raises(ValueError, match="does not exist"):
        rebuild_context_nodes(db_session, 1, user_id=2)


def test_merge_node_context(db_session):
    user = User(id=1, username="testuser", password_hash="hash", is_admin=False, is_active=True)
    db_session.add(user)
    db_session.commit()

    # Root 1 -> 2
    # 2 -> 3 (Branch A)
    # 2 -> 4 (Branch B)
    # Merge 3 and 4 -> 5
    # 5 -> 6 (New question after merge)
    n1 = MessageNode(id=1, user_id=1, parent_id=None, role="user", content="R")
    n2 = MessageNode(id=2, user_id=1, parent_id=1, role="assistant", content="RA")
    n3 = MessageNode(id=3, user_id=1, parent_id=2, role="exchange", content="A", user_content="A", assistant_content="AA")
    n4 = MessageNode(id=4, user_id=1, parent_id=2, role="exchange", content="B", user_content="B", assistant_content="BA")
    n5 = MessageNode(
        id=5,
        user_id=1,
        parent_id=None,
        merge_parent_a_id=3,
        merge_parent_b_id=4,
        role="merge",
        content="Merged synthesis",
        user_content="Merged A and B",
        assistant_content="Combined conclusion of A and B",
    )
    n6 = MessageNode(
        id=6,
        user_id=1,
        parent_id=5,
        role="exchange",
        content="Next",
        user_content="Next",
        assistant_content="Next Answer",
    )
    db_session.add_all([n1, n2, n3, n4, n5, n6])
    db_session.commit()

    context_nodes = rebuild_context_nodes(db_session, 6, user_id=1)
    context_ids = [n.id for n in context_nodes]

    # Shared root 1 and 2 must appear only once
    assert context_ids.count(1) == 1
    assert context_ids.count(2) == 1
    assert 3 in context_ids
    assert 4 in context_ids
    assert 5 in context_ids
    assert context_ids[-1] == 6

    messages = nodes_to_messages(context_nodes)
    # Check that merge node emitted its synthesized assistant message
    merge_msgs = [m for m in messages if m["content"] == "Combined conclusion of A and B"]
    assert len(merge_msgs) == 1
