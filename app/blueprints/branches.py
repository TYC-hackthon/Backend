from flask import Blueprint, request
import json
from sqlalchemy import select
from ..auth import AuthError, require_current_user
from ..database import SessionLocal
from ..http import response_fail, response_ok
from ..models import BranchInfo, MessageNode
from ..services.branch_info import recommend_merge_candidates, upsert_branch_info

branches_bp = Blueprint("branches", __name__, url_prefix="/api")


@branches_bp.get("/branches")
def list_branches():
    try:
        with SessionLocal() as db:
            user = require_current_user(db)
            
            # Fetch all branches for the user
            branches = list(db.scalars(select(BranchInfo).where(BranchInfo.user_id == user.id)))
            
            payload = []
            for b in branches:
                payload.append({
                    "node_id": b.node_id,
                    "summary": b.summary,
                    "tags": json.loads(b.tags) if b.tags else [],
                    "description": b.description,
                    "has_embedding": b.embedding is not None,
                    "embedding_model": b.embedding_model,
                    "created_at": b.created_at.isoformat() if b.created_at else None,
                    "updated_at": b.updated_at.isoformat() if b.updated_at else None,
                })
            
            return response_ok({"branches": payload})
            
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)
    except Exception as exc:
        return response_fail(str(exc), 500)


@branches_bp.get("/branches/<int:node_id>/recommendations")
def get_recommendations(node_id: int):
    try:
        with SessionLocal() as db:
            user = require_current_user(db)
            
        threshold = float(request.args.get("threshold", 0.70))
        limit = int(request.args.get("limit", 10))
        
        candidates = recommend_merge_candidates(node_id, user.id, threshold, limit)
        
        return response_ok({
            "current_node_id": node_id,
            "candidates": candidates
        })
        
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)
    except ValueError as exc:
        return response_fail(str(exc), 400)
    except Exception as exc:
        return response_fail(str(exc), 500)


@branches_bp.get("/branches/compare")
def compare_branches():
    node_a_id = request.args.get("node_a", type=int)
    node_b_id = request.args.get("node_b", type=int)
    
    if not node_a_id or not node_b_id:
        return response_fail("Both node_a and node_b are required.", 400)
        
    try:
        from ..services.embeddings import unpack_embedding, cosine_similarity
        with SessionLocal() as db:
            user = require_current_user(db)
            
            info_a = db.get(BranchInfo, node_a_id)
            info_b = db.get(BranchInfo, node_b_id)
            
            if not info_a or info_a.user_id != user.id:
                return response_fail(f"Branch info for node {node_a_id} does not exist.", 404)
            if not info_b or info_b.user_id != user.id:
                return response_fail(f"Branch info for node {node_b_id} does not exist.", 404)
                
            if not info_a.embedding or not info_b.embedding:
                return response_fail("One or both nodes lack embedding data.", 400)
                
            vec_a = unpack_embedding(info_a.embedding)
            vec_b = unpack_embedding(info_b.embedding)
            sim = cosine_similarity(vec_a, vec_b)
            
            return response_ok({
                "node_a": node_a_id,
                "node_b": node_b_id,
                "similarity": round(sim, 4)
            })
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)
    except Exception as exc:
        return response_fail(str(exc), 500)


@branches_bp.get("/branches/diff")
def branch_diff():
    node_a_id = request.args.get("node_a", type=int)
    node_b_id = request.args.get("node_b", type=int)

    if not node_a_id or not node_b_id:
        return response_fail("Both node_a and node_b are required.", 400)

    try:
        from ..services.message_nodes import calculate_branch_diff
        from ..services.embeddings import unpack_embedding, cosine_similarity

        with SessionLocal() as db:
            user = require_current_user(db)
            diff_result = calculate_branch_diff(db, node_a_id, node_b_id, user.id)

            info_a = db.get(BranchInfo, node_a_id)
            info_b = db.get(BranchInfo, node_b_id)

            similarity = None
            if info_a and info_b and info_a.embedding and info_b.embedding:
                vec_a = unpack_embedding(info_a.embedding)
                vec_b = unpack_embedding(info_b.embedding)
                similarity = round(cosine_similarity(vec_a, vec_b), 4)

            summary_a = info_a.summary if info_a else None
            summary_b = info_b.summary if info_b else None
            tags_a = json.loads(info_a.tags) if (info_a and info_a.tags) else []
            tags_b = json.loads(info_b.tags) if (info_b and info_b.tags) else []

            return response_ok({
                "node_a_id": node_a_id,
                "node_b_id": node_b_id,
                "similarity": similarity,
                "lca_node": diff_result["lca_node"],
                "branch_a_nodes": diff_result["branch_a_nodes"],
                "branch_b_nodes": diff_result["branch_b_nodes"],
                "summary_a": summary_a,
                "summary_b": summary_b,
                "tags_a": tags_a,
                "tags_b": tags_b,
            })
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)
    except ValueError as exc:
        return response_fail(str(exc), 404)
    except RuntimeError as exc:
        return response_fail(str(exc), 500)
    except Exception as exc:
        return response_fail(str(exc), 500)


@branches_bp.patch("/branches/<int:node_id>")
def update_branch(node_id: int):
    payload = request.get_json(silent=True) or {}
    description = payload.get("description")
    tags = payload.get("tags")

    try:
        with SessionLocal() as db:
            user = require_current_user(db)
            
            with db.begin():
                branch = db.get(BranchInfo, node_id)
                if not branch or branch.user_id != user.id:
                    return response_fail(f"Branch info for node {node_id} does not exist.", 404)
                
                if description is not None:
                    branch.description = description
                
                if tags is not None:
                    if not isinstance(tags, list):
                        return response_fail("tags must be a list of strings", 400)
                    branch.tags = json.dumps([str(t) for t in tags])
                
                db.flush()
                
                return response_ok({
                    "node_id": branch.node_id,
                    "description": branch.description,
                    "tags": json.loads(branch.tags) if branch.tags else [],
                    "summary": branch.summary,
                    "has_embedding": branch.embedding is not None,
                })
                
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)
    except Exception as exc:
        return response_fail(str(exc), 500)


@branches_bp.post("/branches/<int:node_id>/recompute")
def recompute_branch(node_id: int):
    payload = request.get_json(silent=True) or {}
    ollama_base_url = payload.get("ollama_base_url")
    provider = payload.get("provider", "ollama")
    metadata_model = payload.get("metadata_model") or payload.get("model")

    try:
        with SessionLocal() as db:
            user = require_current_user(db)
            
            # Check if node exists and belongs to user
            node = db.get(MessageNode, node_id)
            if not node or node.user_id != user.id:
                return response_fail(f"Node {node_id} does not exist.", 404)
        
        # This will create or update the BranchInfo with a new embedding
        upsert_branch_info(
            node_id,
            user.id,
            provider=provider,
            metadata_model=metadata_model,
            ollama_base_url=ollama_base_url,
        )
        
        with SessionLocal() as db:
            branch = db.get(BranchInfo, node_id)
            
            return response_ok({
                "node_id": node_id,
                "recomputed": ["embedding"],
                "embedding_model": branch.embedding_model if branch else None,
                "embedding_dim": branch.embedding_dim if branch else None,
                "has_embedding": branch.embedding is not None if branch else False,
            })
            
    except AuthError as exc:
        return response_fail(str(exc), exc.status_code)
    except Exception as exc:
        return response_fail(str(exc), 500)
