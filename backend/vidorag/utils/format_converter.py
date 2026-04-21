import json
import os
from llama_index.core.schema import TextNode, NodeRelationship, RelatedNodeInfo, ImageNode
from llama_index.core import Document
from typing import Optional, List, Mapping, Any, Dict


def nodes2dict(nodes) -> List[Dict[str, Any]]:
    resp_dict = {
        "response": None,
        "source_nodes": [],
        "metadata": None
    }
    for node in nodes:
        resp_dict["source_nodes"].append(node.to_dict())
    return resp_dict


def nodefile2node(input_file):
    nodes = []
    for doc in json.load(open(input_file, 'r')):
        if doc['class_name'] == 'TextNode' and doc['text'] != '':
            nodes.append(TextNode.from_dict(doc))
        elif doc['class_name'] == 'ImageNode':
            nodes.append(ImageNode.from_dict(doc))
        else:
            continue
    return nodes
