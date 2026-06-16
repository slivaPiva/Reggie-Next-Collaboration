import globals_
import base64
import uuid
import copy

class UndoStack:
    """
    A stack you can push UndoActions on, and stuff.
    """

    def __init__(self):
        self.pastActions = []
        self.futureActions = []

    def addAction(self, act):
        """
        Adds an action to the stack
        """
        self.pastActions.append(act)
        self.futureActions = []

        self.enableOrDisableMenuItems()
        self._collabHistoryAdded(act)

    def addOrExtendAction(self, act):
        """
        Adds an action to the stack, or extends the current one if applicable
        """
        if self.pastActions and self.pastActions[-1].isExtentionOf(act):
            self.pastActions[-1].extend(act)
            self.enableOrDisableMenuItems()
            self._collabHistoryUpdated(self.pastActions[-1])
        else:
            self.addAction(act)

    def clear(self):
        self.pastActions = []
        self.futureActions = []
        self.enableOrDisableMenuItems()

    def undo(self):
        """
        Undoes the last action
        """
        if not self.pastActions: return

        act = self.pastActions.pop()
        while act.isNull():
            # Keep popping null actions off
            if not self.pastActions:
                return
            act = self.pastActions.pop()

        mw = getattr(globals_, 'mainWindow', None)
        if mw is not None:
            mw.UndoRedoInProgress = True
        try:
            act.undo()
        finally:
            if mw is not None:
                mw.UndoRedoInProgress = False
        self.futureActions.append(act)

        self.enableOrDisableMenuItems()

    def redo(self):
        """
        Redoes the last undone action
        """
        if not self.futureActions: return

        act = self.futureActions.pop()
        while act.isNull():
            # Keep popping null actions off
            act = self.futureActions.pop()

        mw = getattr(globals_, 'mainWindow', None)
        if mw is not None:
            mw.UndoRedoInProgress = True
        try:
            act.redo()
        finally:
            if mw is not None:
                mw.UndoRedoInProgress = False
        self.pastActions.append(act)

        self.enableOrDisableMenuItems()

    def enableOrDisableMenuItems(self):
        """
        Enables or disables the menu items of mainWindow
        """
        globals_.mainWindow.actions['undo'].setEnabled(bool(self.pastActions))
        globals_.mainWindow.actions['redo'].setEnabled(bool(self.futureActions))

    def _collabHistoryAdded(self, act):
        mw = getattr(globals_, 'mainWindow', None)
        cb = getattr(mw, 'CollabHistoryActionAdded', None) if mw is not None else None
        if cb is not None:
            try:
                cb(act)
            except Exception:
                pass

    def _collabHistoryUpdated(self, act):
        mw = getattr(globals_, 'mainWindow', None)
        cb = getattr(mw, 'CollabHistoryActionUpdated', None) if mw is not None else None
        if cb is not None:
            try:
                cb(act)
            except Exception:
                pass


class UndoAction:
    """
    Abstract undo action
    """

    def undo(self):
        """
        Sets the target to its initial state
        """
        pass

    def redo(self):
        """
        Sets the target to its final state
        """
        pass

    def isExtentionOf(self, other):
        """
        Returns True if this action extends another, else False
        """
        return False

    def extend(self, other):
        """
        Extends this UndoAction with the data from an extention of it.
        isExtentionOf must have returned True first!
        """
        pass

    def isNull(self):
        """
        Returns True if this action is effectively a no-op
        """
        return True

    def serialize(self):
        return {}

    @classmethod
    def deserialize(cls, data):
        return None


class MoveItemUndoAction(UndoAction):
    """
    An UndoAction for movement of a single level item that is not an object
    """

    def __init__(self, target, origX, origY, finalX, finalY):
        """
        Initializes the undo action
        """
        mw = getattr(globals_, 'mainWindow', None)
        try:
            cid = getattr(mw, '_CollabEnsureItemId', None) if mw is not None else None
            if cid is not None:
                cid(target)
        except Exception:
            pass
        defType = target.instanceDef
        self.origDef = defType(target)
        self.finalDef = defType(target)
        self.origDef.objx = origX
        self.origDef.objy = origY
        self.finalDef.objx = finalX
        self.finalDef.objy = finalY
        self.collab_id = str(getattr(target, '_collab_id', '') or '')
        self.action_id = uuid.uuid4().hex

    def _find_instance(self, prefer_final=True):
        """
        Ищет живой инстанс для действия перемещения.
        prefer_final=True: сначала ищем по finalDef (для undo)
        prefer_final=False: сначала ищем по origDef (для redo)
        """
        instance = _find_instance_by_collab_id(self.collab_id) if self.collab_id else None
        if instance is not None:
            return instance
        try:
            primary = self.finalDef if prefer_final else self.origDef
            secondary = self.origDef if prefer_final else self.finalDef
        except Exception:
            return None
        try:
            instance = primary.findInstance()
        except Exception:
            instance = None
        if instance is not None:
            return instance
        try:
            return secondary.findInstance()
        except Exception:
            return None

    def undo(self):
        """
        Sets the target object's position to the original position
        """
        instance = self._find_instance(prefer_final=True)
        if instance:
            self.changeObjectPos(instance, self.origDef.objx, self.origDef.objy)
        else:
            print('Undo Move Item: Cannot find item instance! ' + str(self.finalDef))

    def redo(self):
        """
        Sets the target object's position to the final position
        """
        instance = self._find_instance(prefer_final=False)
        if instance:
            self.changeObjectPos(instance, self.finalDef.objx, self.finalDef.objy)
        else:
            print('Redo Move Item: Cannot find item instance! ' + str(self.origDef))

    @staticmethod
    def changeObjectPos(obj, newX, newY):
        """
        Changes the position of an object
        """
        from levelitems import SpriteItem, ObjectItem, PathItem

        if isinstance(obj, SpriteItem):
            # Sprites are weird so they handle this themselves
            obj.setNewObjPos(newX, newY)

        elif isinstance(obj, ObjectItem):
            # Objects use the objx and objy properties differently
            oldBR = obj.getFullRect()

            obj.objx, obj.objy = newX, newY
            obj.setPos(newX * 24, newY * 24)
            obj.UpdateRects()

            newBR = obj.getFullRect()

            globals_.mainWindow.scene.update(oldBR)
            globals_.mainWindow.scene.update(newBR)

        elif isinstance(obj, PathItem):
            obj.objx, obj.objy = newX, newY
            obj.setPos(newX * 1.5, newY * 1.5)
            obj.updatePos()

        else:
            # Everything else is normal
            obj.objx, obj.objy = newX, newY
            obj.setPos(newX * 1.5, newY * 1.5)

        globals_.mainWindow.levelOverview.update()

        # Collaboration: propagate undo/redo result as delta ops.
        mw = getattr(globals_, 'mainWindow', None)
        if mw is None:
            return
        try:
            if not getattr(mw, '_CollabEnabled', lambda: False)():
                return
        except Exception:
            return
        try:
            from levelitems import SpriteItem, ObjectItem, EntranceItem, LocationItem, CommentItem
        except Exception:
            SpriteItem = ObjectItem = EntranceItem = LocationItem = CommentItem = None
        try:
            if SpriteItem is not None and isinstance(obj, SpriteItem):
                mw.CollabQueueSpriteUpdate(obj, include_data=False)
            elif ObjectItem is not None and isinstance(obj, ObjectItem):
                mw.CollabQueueObjectUpdate(obj)
            elif EntranceItem is not None and isinstance(obj, EntranceItem):
                mw.CollabQueueEntranceUpsert(obj, is_add=False)
            elif LocationItem is not None and isinstance(obj, LocationItem):
                mw.CollabQueueLocationUpsert(obj, is_add=False)
            elif CommentItem is not None and isinstance(obj, CommentItem):
                mw.CollabQueueCommentUpsert(obj, is_add=False)
        except Exception:
            pass

    def isExtentionOf(self, other):
        """
        Returns True if this MoveItemUndoAction extends another
        """
        return hasattr(other, 'origDef') and self.origDef.defMatchesData(other.origDef) and str(getattr(self, 'collab_id', '')) == str(getattr(other, 'collab_id', ''))

    def extend(self, other):
        """
        Extends this MoveItemUndoAction with the data from an extention of it.
        isExtentionOf must have returned True first!
        """
        self.finalDef.objx = other.finalDef.objx
        self.finalDef.objy = other.finalDef.objy

    def isNull(self):
        """
        Returns True if this action is effectively a no-op
        """
        if self.origDef.objx == self.finalDef.objx and self.origDef.objy == self.finalDef.objy:
            return True
        # Если инстанс уже отсутствует, этот move больше нечего применять.
        # Это позволяет UndoStack пропустить "мертвое" перемещение за один Ctrl+Z,
        # вместо лишней ошибки и второго нажатия.
        return self._find_instance(prefer_final=True) is None

    def serialize(self):
        return {
            'kind': 'move',
            'id': self.action_id,
            'collab_id': self.collab_id,
            'orig': _instance_def_to_dict(self.origDef),
            'final': _instance_def_to_dict(self.finalDef),
        }

    @classmethod
    def deserialize(cls, data):
        orig = _instance_def_from_dict(data.get('orig') or {})
        final = _instance_def_from_dict(data.get('final') or {})
        act = cls.__new__(cls)
        act.origDef = orig
        act.finalDef = final
        act.collab_id = str(data.get('collab_id') or '')
        act.action_id = str(data.get('id') or uuid.uuid4().hex)
        return act


class SimultaneousUndoAction(UndoAction):
    """
    An undo action that consists of multiple undo actions at once
    """

    def __init__(self, children):
        """
        Initializes the undo action
        """
        # ВАЖНО: порядок выполнения имеет значение (например при восстановлении
        # нескольких узлов Path по индексам). set() делает порядок случайным и
        # ломает node id/порядок сегментов после undo/redo.
        self.children = list(children) if isinstance(children, (list, tuple, set)) else []
        self.action_id = uuid.uuid4().hex

    def _iter_children(self, is_undo):
        """
        Возвращает детей в безопасном порядке для undo/redo.
        Для PathNodeUndoAction корректируем порядок по индексу, чтобы вставки/удаления
        не сдвигали индексы следующих операций.
        """
        children = list(self.children)
        try:
            # PathNodeUndoAction объявлен ниже в этом же модуле
            pcls = PathNodeUndoAction
        except Exception:
            pcls = None

        if pcls is None:
            return children

        def sort_key(act):
            if isinstance(act, pcls):
                try:
                    pid = int(getattr(act, 'path_id', 0))
                except Exception:
                    pid = 0
                try:
                    idx = int(getattr(act, 'node_index', 0))
                except Exception:
                    idx = 0

                # Если сейчас undo:
                # - op == 'delete' -> мы создаём узлы: создавать нужно по возрастанию индексов
                # - op == 'create' -> мы удаляем узлы: удалять нужно по убыванию индексов
                #
                # Если сейчас redo:
                # - op == 'create' -> мы создаём узлы: по возрастанию
                # - op == 'delete' -> мы удаляем узлы: по убыванию
                op = str(getattr(act, 'op', '') or '')
                creating = (op == 'delete') if is_undo else (op == 'create')
                idx_key = idx if creating else -idx
                return (0, pid, idx_key)

            # Остальные действия выполняем после path-узлов в исходном порядке
            return (1, 0, 0)

        try:
            children.sort(key=sort_key)
        except Exception:
            pass
        return children

    def undo(self):
        """
        Calls undo() on all children
        """
        for c in self._iter_children(is_undo=True):
            c.undo()

    def redo(self):
        """
        Calls redo() on all children
        """
        for c in self._iter_children(is_undo=False):
            c.redo()

    def isExtentionOf(self, other):
        """
        Returns True if this SinultaneousUndoAction and another one have equivalent children
        """
        if not hasattr(other, 'children'): return False
        searchIn = list(self.children)
        searchAgainst = list(getattr(other, 'children', []) or [])
        for searchInObj in searchIn:
            found = False
            for searchAgainstObj in list(searchAgainst):
                if searchAgainstObj.isExtentionOf(searchInObj):
                    found = True
                    try:
                        searchAgainst.remove(searchAgainstObj)
                    except Exception:
                        pass
                    break  # only breaks out of inner loop
            if not found:
                return False
        return True

    def extend(self, other):
        """
        Extend this SimultaneousUndoAction with the data from an extention of it.
        isExtentionOf must have returned True first!
        """
        searchMine = list(self.children)
        searchOther = list(getattr(other, 'children', []) or [])
        for searchMineObj in searchMine:
            for searchOtherObj in searchOther:
                if searchOtherObj.isExtentionOf(searchMineObj):
                    searchMineObj.extend(searchOtherObj)
                    try:
                        searchOther.remove(searchOtherObj)
                    except Exception:
                        pass
                    break  # only breaks out of inner loop

    def isNull(self):
        """
        Returns True if this action is effectively a no-op
        """
        return all(c.isNull() for c in self.children)

    def serialize(self):
        return {
            'kind': 'simul',
            'id': self.action_id,
            'children': [serialize_undo_action(c) for c in self.children],
        }

    @classmethod
    def deserialize(cls, data):
        children_raw = data.get('children')
        children = []
        for c in children_raw if isinstance(children_raw, list) else []:
            act = deserialize_undo_action(c)
            if act is not None:
                children.append(act)
        act = cls(children)
        act.action_id = str(data.get('id') or uuid.uuid4().hex)
        return act


class CreateOrDeleteInstanceUndoAction(UndoAction):
    def __init__(self, op, inst_def, collab_id=None, extra=None, action_id=None):
        self.op = str(op)
        self.inst_def = inst_def
        self.collab_id = str(collab_id) if collab_id else ''
        self.extra = extra or {}
        self.action_id = str(action_id or uuid.uuid4().hex)

    def undo(self):
        if self.op == 'create':
            _delete_instance(self.inst_def, self.collab_id)
        else:
            _create_instance(self.inst_def, self.collab_id, self.extra)

    def redo(self):
        if self.op == 'create':
            _create_instance(self.inst_def, self.collab_id, self.extra)
        else:
            _delete_instance(self.inst_def, self.collab_id)

    def isNull(self):
        return False

    def serialize(self):
        return {
            'kind': 'inst',
            'id': self.action_id,
            'op': self.op,
            'def': _instance_def_to_dict(self.inst_def),
            'collab_id': self.collab_id,
            'extra': self.extra,
        }

    @classmethod
    def deserialize(cls, data):
        inst_def = _instance_def_from_dict(data.get('def') or {})
        if inst_def is None:
            return None
        return cls(
            data.get('op') or 'create',
            inst_def,
            collab_id=data.get('collab_id') or '',
            extra=data.get('extra') if isinstance(data.get('extra'), dict) else {},
            action_id=data.get('id') or None,
        )


class PathNodeUndoAction(UndoAction):
    def __init__(self, op, path_id, node_index, node_data, loops=False, node_collab_id=None, action_id=None):
        self.op = str(op)
        self.path_id = int(path_id)
        self.node_index = int(node_index)
        self.node_data = node_data
        self.loops = bool(loops)
        self.node_collab_id = str(node_collab_id) if node_collab_id else ''
        self.action_id = str(action_id or uuid.uuid4().hex)

    def undo(self):
        if self.op == 'create':
            _delete_path_node(self.path_id, self.node_index, self.node_collab_id)
        else:
            _create_path_node(self.path_id, self.node_index, self.node_data, self.loops, self.node_collab_id)

    def redo(self):
        if self.op == 'create':
            _create_path_node(self.path_id, self.node_index, self.node_data, self.loops, self.node_collab_id)
        else:
            _delete_path_node(self.path_id, self.node_index, self.node_collab_id)

    def isNull(self):
        return False

    def serialize(self):
        return {
            'kind': 'path_node',
            'id': self.action_id,
            'op': self.op,
            'path_id': self.path_id,
            'node_index': self.node_index,
            'node': self.node_data,
            'loops': self.loops,
            'node_collab_id': self.node_collab_id,
        }

    @classmethod
    def deserialize(cls, data):
        return cls(
            data.get('op') or 'create',
            int(data.get('path_id', 0)),
            int(data.get('node_index', 0)),
            data.get('node') if isinstance(data.get('node'), (list, tuple)) and len(data.get('node')) == 5 else (0, 0, 0.5, 0.00498, 0),
            bool(data.get('loops', False)),
            node_collab_id=str(data.get('node_collab_id') or ''),
            action_id=data.get('id') or None,
        )


class ZoneUndoAction(UndoAction):
    def __init__(self, op, zone_data, action_id=None):
        self.op = str(op)
        self.zone_data = zone_data
        self.action_id = str(action_id or uuid.uuid4().hex)

    def undo(self):
        if self.op == 'create':
            _delete_zone(self.zone_data)
        else:
            _create_zone(self.zone_data)

    def redo(self):
        if self.op == 'create':
            _create_zone(self.zone_data)
        else:
            _delete_zone(self.zone_data)

    def isNull(self):
        return False

    def serialize(self):
        return {
            'kind': 'zone',
            'id': self.action_id,
            'op': self.op,
            'zone': self.zone_data,
        }

    @classmethod
    def deserialize(cls, data):
        zone = data.get('zone')
        if not isinstance(zone, dict):
            return None
        return cls(data.get('op') or 'create', zone, action_id=data.get('id') or None)


def _encode_field_value(value):
    if isinstance(value, bytes):
        return {'__bytes__': base64.b64encode(value).decode('ascii')}
    return value


def _decode_field_value(value):
    if isinstance(value, dict) and '__bytes__' in value:
        try:
            return base64.b64decode(value.get('__bytes__') or '')
        except Exception:
            return b''
    return value


def _instance_def_to_dict(inst_def):
    if inst_def is None:
        return {}
    return {
        'type': inst_def.__class__.__name__,
        'objx': inst_def.objx,
        'objy': inst_def.objy,
        'fields': [[name, _encode_field_value(val)] for name, val in getattr(inst_def, 'fields', [])],
    }


def _instance_def_from_dict(data):
    if not isinstance(data, dict):
        return None
    type_name = data.get('type')
    if not type_name:
        return None
    try:
        import levelitems
        cls = getattr(levelitems, type_name, None)
    except Exception:
        cls = None
    if cls is None:
        return None
    inst = cls()
    inst.objx = data.get('objx')
    inst.objy = data.get('objy')
    fields_in = data.get('fields')
    if isinstance(fields_in, list):
        name_map = {name: idx for idx, (name, _) in enumerate(getattr(inst, 'fields', []))}
        for entry in fields_in:
            if not isinstance(entry, list) or len(entry) != 2:
                continue
            name, val = entry
            idx = name_map.get(name)
            if idx is None:
                continue
            inst.fields[idx][1] = _decode_field_value(val)
    return inst


def serialize_undo_action(act):
    if act is None:
        return None
    try:
        return act.serialize()
    except Exception:
        return None


def deserialize_undo_action(data):
    if not isinstance(data, dict):
        return None
    kind = data.get('kind')
    if kind == 'move':
        return MoveItemUndoAction.deserialize(data)
    if kind == 'simul':
        return SimultaneousUndoAction.deserialize(data)
    if kind == 'inst':
        return CreateOrDeleteInstanceUndoAction.deserialize(data)
    if kind == 'path_node':
        return PathNodeUndoAction.deserialize(data)
    if kind == 'zone':
        return ZoneUndoAction.deserialize(data)
    if kind == 'mod_inst':
        return ModifyInstanceUndoAction.deserialize(data)
    if kind == 'path_state':
        return PathStateUndoAction.deserialize(data)
    return None


def _find_instance_by_collab_id(collab_id):
    if not collab_id:
        return None
    if globals_.Area is None:
        return None
    cid = str(collab_id)
    for layer in getattr(globals_.Area, 'layers', [])[:3]:
        for obj in layer:
            if str(getattr(obj, '_collab_id', '')) == cid:
                return obj
    for spr in getattr(globals_.Area, 'sprites', []):
        if str(getattr(spr, '_collab_id', '')) == cid:
            return spr
    for ent in getattr(globals_.Area, 'entrances', []):
        if str(getattr(ent, '_collab_id', '')) == cid:
            return ent
    for loc in getattr(globals_.Area, 'locations', []):
        if str(getattr(loc, '_collab_id', '')) == cid:
            return loc
    for com in getattr(globals_.Area, 'comments', []):
        if str(getattr(com, '_collab_id', '')) == cid:
            return com
    for path in getattr(globals_.Area, 'paths', []):
        for node in getattr(path, '_nodes', []):
            if str(getattr(node, '_collab_id', '')) == cid:
                return node
    return None


def _apply_instance_def_to_existing(inst, inst_def):
    if inst is None or inst_def is None:
        return
    mw = getattr(globals_, 'mainWindow', None)
    if mw is None:
        return
    tname = inst_def.__class__.__name__
    if tname == 'InstanceDefinition_SpriteItem':
        inst.spritedata = inst_def.fields[1][1]
        try:
            inst.UpdateDynamicSizing()
        except Exception:
            pass
        try:
            inst.UpdateListItem()
        except Exception:
            pass
        try:
            mw.spriteList.updateSprite(inst)
        except Exception:
            pass
    elif tname == 'InstanceDefinition_EntranceItem':
        inst.autoPosChange = True
        try:
            old_type = int(getattr(inst, 'enttype', 0))
            inst.entid = int(inst_def.fields[0][1])
            inst.destarea = int(inst_def.fields[1][1])
            inst.destentrance = int(inst_def.fields[2][1])
            inst.enttype = int(inst_def.fields[3][1])
            inst.entzone = int(inst_def.fields[4][1])
            inst.entlayer = int(inst_def.fields[5][1])
            inst.entpath = int(inst_def.fields[6][1])
            inst.cpdirection = int(inst_def.fields[7][1])
            inst.entsettings = int(inst_def.fields[8][1])
            inst.UpdateRects()
            if int(getattr(inst, 'enttype', 0)) != old_type:
                inst.aux.TypeChange()
            inst.UpdateTooltip()
            inst.UpdateListItem()
            inst.update()
        finally:
            inst.autoPosChange = False
    elif tname == 'InstanceDefinition_LocationItem':
        inst.autoPosChange = True
        try:
            inst.objx = int(inst_def.objx)
            inst.objy = int(inst_def.objy)
            inst.width = int(inst_def.fields[0][1])
            inst.height = int(inst_def.fields[1][1])
            inst.id = int(inst_def.fields[2][1])
            inst.setPos(int(inst.objx * 1.5), int(inst.objy * 1.5))
            inst.UpdateTitle()
            inst.UpdateRects()
            inst.UpdateListItem()
            inst.update()
        finally:
            inst.autoPosChange = False
    elif tname == 'InstanceDefinition_CommentItem':
        try:
            inst.text = str(inst_def.fields[0][1])
        except Exception:
            pass
        try:
            inst.UpdateTooltip()
        except Exception:
            pass
        try:
            inst.UpdateListItem()
        except Exception:
            pass
        try:
            inst.update()
        except Exception:
            pass

    # Collaboration: propagate property edits as delta ops (not full meta state).
    try:
        if hasattr(mw, '_CollabEnabled') and mw._CollabEnabled():
            from levelitems import SpriteItem, EntranceItem, LocationItem, CommentItem
            if isinstance(inst, SpriteItem):
                mw.CollabQueueSpriteUpdate(inst, include_data=True)
            elif isinstance(inst, EntranceItem):
                mw.CollabQueueEntranceUpsert(inst, is_add=False)
            elif isinstance(inst, LocationItem):
                mw.CollabQueueLocationUpsert(inst, is_add=False)
            elif isinstance(inst, CommentItem):
                mw.CollabQueueCommentUpsert(inst, is_add=False)
    except Exception:
        pass
    try:
        from dirty import SetDirty
        SetDirty()
    except Exception:
        pass
    try:
        mw.levelOverview.update()
    except Exception:
        pass
    try:
        mw.UpdatePipeEntranceLinks()
    except Exception:
        pass


class ModifyInstanceUndoAction(UndoAction):
    def __init__(self, before_def, after_def, collab_id=None, action_id=None):
        self.before_def = before_def
        self.after_def = after_def
        self.collab_id = str(collab_id) if collab_id else ''
        self.action_id = str(action_id or uuid.uuid4().hex)

    def undo(self):
        inst = _find_instance_by_collab_id(self.collab_id) if self.collab_id else None
        if inst is None:
            try:
                inst = self.after_def.findInstance()
            except Exception:
                inst = None
        _apply_instance_def_to_existing(inst, self.before_def)

    def redo(self):
        inst = _find_instance_by_collab_id(self.collab_id) if self.collab_id else None
        if inst is None:
            try:
                inst = self.before_def.findInstance()
            except Exception:
                inst = None
        _apply_instance_def_to_existing(inst, self.after_def)

    def isNull(self):
        try:
            return self.before_def.defMatches(self.after_def)
        except Exception:
            return False

    def isExtentionOf(self, other):
        return (
            hasattr(other, 'collab_id')
            and str(getattr(self, 'collab_id', '')) == str(getattr(other, 'collab_id', ''))
            and getattr(getattr(self, 'before_def', None), '__class__', None) == getattr(getattr(other, 'before_def', None), '__class__', None)
        )

    def extend(self, other):
        self.after_def = getattr(other, 'after_def', self.after_def)

    def serialize(self):
        return {
            'kind': 'mod_inst',
            'id': self.action_id,
            'collab_id': self.collab_id,
            'before': _instance_def_to_dict(self.before_def),
            'after': _instance_def_to_dict(self.after_def),
        }

    @classmethod
    def deserialize(cls, data):
        before = _instance_def_from_dict(data.get('before') or {})
        after = _instance_def_from_dict(data.get('after') or {})
        if before is None or after is None:
            return None
        return cls(before, after, collab_id=data.get('collab_id') or '', action_id=data.get('id') or None)


class PathStateUndoAction(UndoAction):
    def __init__(self, before_paths, after_paths, action_id=None):
        # В истории храним независимые снапшоты (deepcopy), чтобы:
        # 1) дальнейшие мутации списков/словарей не портили "прошлое"
        # 2) undo/redo не начинал работать с уже изменёнными структурами
        try:
            self.before_paths = copy.deepcopy(before_paths) if isinstance(before_paths, list) else []
        except Exception:
            self.before_paths = list(before_paths) if isinstance(before_paths, list) else []
        try:
            self.after_paths = copy.deepcopy(after_paths) if isinstance(after_paths, list) else []
        except Exception:
            self.after_paths = list(after_paths) if isinstance(after_paths, list) else []
        self.action_id = str(action_id or uuid.uuid4().hex)

    def undo(self):
        mw = getattr(globals_, 'mainWindow', None)
        if mw is None:
            return
        try:
            mw.ReplaceAreaPathsFromState({'paths': self.before_paths})
        except Exception:
            pass

    def redo(self):
        mw = getattr(globals_, 'mainWindow', None)
        if mw is None:
            return
        try:
            mw.ReplaceAreaPathsFromState({'paths': self.after_paths})
        except Exception:
            pass

    def isNull(self):
        return self.before_paths == self.after_paths

    def isExtentionOf(self, other):
        return hasattr(other, 'before_paths') and getattr(self, 'before_paths', None) == getattr(other, 'before_paths', None)

    def extend(self, other):
        try:
            nxt = getattr(other, 'after_paths', self.after_paths)
            self.after_paths = copy.deepcopy(nxt) if isinstance(nxt, list) else self.after_paths
        except Exception:
            self.after_paths = getattr(other, 'after_paths', self.after_paths)

    def serialize(self):
        return {
            'kind': 'path_state',
            'id': self.action_id,
            'before': self.before_paths,
            'after': self.after_paths,
        }

    @classmethod
    def deserialize(cls, data):
        before = data.get('before')
        after = data.get('after')
        if not isinstance(before, list) or not isinstance(after, list):
            return None
        return cls(before, after, action_id=data.get('id') or None)


def _delete_instance(inst_def, collab_id):
    mw = getattr(globals_, 'mainWindow', None)
    if mw is None or globals_.Area is None:
        return
    inst = _find_instance_by_collab_id(collab_id) if collab_id else None
    if inst is None and inst_def is not None:
        try:
            inst = inst_def.findInstance()
        except Exception:
            inst = None
    if inst is None:
        return

    # Collaboration: emit delete as delta op before removing the instance.
    try:
        if collab_id and not getattr(inst, '_collab_id', None):
            inst._collab_id = str(collab_id)
    except Exception:
        pass
    try:
        if hasattr(mw, '_CollabEnabled') and mw._CollabEnabled():
            from levelitems import ObjectItem, SpriteItem, EntranceItem, LocationItem, CommentItem
            if isinstance(inst, ObjectItem):
                mw.CollabQueueObjectDelete(inst)
            elif isinstance(inst, SpriteItem):
                mw.CollabQueueSpriteDelete(inst)
            elif isinstance(inst, EntranceItem):
                mw.CollabQueueEntranceDelete(inst)
            elif isinstance(inst, LocationItem):
                mw.CollabQueueLocationDelete(inst)
            elif isinstance(inst, CommentItem):
                mw.CollabQueueCommentDelete(inst)
    except Exception:
        pass

    try:
        inst.delete()
    except Exception:
        pass
    try:
        mw.scene.removeItem(inst)
    except Exception:
        pass
    try:
        from dirty import SetDirty
        SetDirty()
    except Exception:
        pass
    try:
        mw.levelOverview.update()
    except Exception:
        pass


def _create_instance(inst_def, collab_id, extra):
    mw = getattr(globals_, 'mainWindow', None)
    if mw is None or globals_.Area is None or inst_def is None:
        return None
    tname = inst_def.__class__.__name__
    existing = _find_instance_by_collab_id(collab_id) if collab_id else None
    if existing is not None:
        if tname != 'InstanceDefinition_ObjectItem':
            try:
                _apply_instance_def_to_existing(existing, inst_def)
            except Exception:
                pass
        if 'z' in extra:
            try:
                existing.setZValue(float(extra.get('z')))
            except Exception:
                pass
        return existing
    created = None
    if tname == 'InstanceDefinition_ObjectItem':
        tileset = int(inst_def.fields[0][1])
        obj_type = int(inst_def.fields[1][1])
        layer = int(inst_def.fields[2][1])
        width = int(inst_def.fields[3][1])
        height = int(inst_def.fields[4][1])
        # Prevent CreateObject from auto-emitting collaboration ops with a fresh id.
        prev_block = bool(getattr(mw, 'collabApplyingRemoteHistory', False))
        mw.collabApplyingRemoteHistory = True
        try:
            created = mw.CreateObject(tileset, obj_type, layer, int(inst_def.objx), int(inst_def.objy), width, height, add_to_scene=True)
        finally:
            mw.collabApplyingRemoteHistory = prev_block
        if created is not None and collab_id:
            created._collab_id = str(collab_id)
            try:
                mw._collabObjectById[str(collab_id)] = created
            except Exception:
                pass
            # Emit authoritative add op with the correct collab id.
            try:
                if hasattr(mw, '_CollabEnabled') and mw._CollabEnabled():
                    mw._QueueCollabOp({
                        'op': 'obj_add',
                        'id': str(collab_id),
                        'layer': int(getattr(created, 'layer', layer)),
                        'tileset': int(getattr(created, 'tileset', tileset)),
                        'type': int(getattr(created, 'type', obj_type)),
                        'x': int(getattr(created, 'objx', int(inst_def.objx))),
                        'y': int(getattr(created, 'objy', int(inst_def.objy))),
                        'w': int(getattr(created, 'width', width)),
                        'h': int(getattr(created, 'height', height)),
                    })
            except Exception:
                pass
        if created is not None and 'z' in extra:
            try:
                created.setZValue(float(extra.get('z')))
            except Exception:
                pass
    elif tname == 'InstanceDefinition_SpriteItem':
        spr_type = int(inst_def.fields[0][1])
        spr_data = inst_def.fields[1][1]
        prev_block = bool(getattr(mw, 'collabApplyingRemoteHistory', False))
        mw.collabApplyingRemoteHistory = True
        try:
            created = mw.CreateSprite(int(inst_def.objx), int(inst_def.objy), spr_type, spr_data, add_to_scene=True)
        finally:
            mw.collabApplyingRemoteHistory = prev_block
        if created is not None and collab_id:
            created._collab_id = str(collab_id)
            try:
                mw._collabSpriteById[str(collab_id)] = created
            except Exception:
                pass
            try:
                if hasattr(mw, '_CollabEnabled') and mw._CollabEnabled():
                    mw._QueueCollabOp({
                        'op': 'spr_add',
                        'id': str(collab_id),
                        'type': int(getattr(created, 'type', spr_type)),
                        'x': int(getattr(created, 'objx', int(inst_def.objx))),
                        'y': int(getattr(created, 'objy', int(inst_def.objy))),
                        'data': base64.b64encode(getattr(created, 'spritedata', bytes())).decode('ascii'),
                    })
            except Exception:
                pass
    elif tname == 'InstanceDefinition_EntranceItem':
        entid = int(inst_def.fields[0][1])
        prev_block = bool(getattr(mw, 'collabApplyingRemoteHistory', False))
        mw.collabApplyingRemoteHistory = True
        try:
            created = mw.CreateEntrance(int(inst_def.objx), int(inst_def.objy), id_=entid, add_to_scene=True)
        finally:
            mw.collabApplyingRemoteHistory = prev_block
        if created is not None and collab_id:
            created._collab_id = collab_id
        if created is not None:
            created.autoPosChange = True
            try:
                created.destarea = int(inst_def.fields[1][1])
                created.destentrance = int(inst_def.fields[2][1])
                created.enttype = int(inst_def.fields[3][1])
                created.entzone = int(inst_def.fields[4][1])
                created.entlayer = int(inst_def.fields[5][1])
                created.entpath = int(inst_def.fields[6][1])
                created.cpdirection = int(inst_def.fields[7][1])
                created.entsettings = int(inst_def.fields[8][1])
                created.UpdateRects()
                created.aux.TypeChange()
                created.UpdateTooltip()
                created.UpdateListItem()
            finally:
                created.autoPosChange = False
            try:
                if hasattr(mw, '_CollabEnabled') and mw._CollabEnabled():
                    mw.CollabQueueEntranceUpsert(created, is_add=True)
            except Exception:
                pass
    elif tname == 'InstanceDefinition_LocationItem':
        width = int(inst_def.fields[0][1])
        height = int(inst_def.fields[1][1])
        locid = int(inst_def.fields[2][1])
        prev_block = bool(getattr(mw, 'collabApplyingRemoteHistory', False))
        mw.collabApplyingRemoteHistory = True
        try:
            created = mw.CreateLocation(int(inst_def.objx), int(inst_def.objy), width, height, id_=locid, add_to_scene=True)
        finally:
            mw.collabApplyingRemoteHistory = prev_block
        if created is not None and collab_id:
            created._collab_id = collab_id
        if created is not None:
            try:
                if hasattr(mw, '_CollabEnabled') and mw._CollabEnabled():
                    mw.CollabQueueLocationUpsert(created, is_add=True)
            except Exception:
                pass
    elif tname == 'InstanceDefinition_CommentItem':
        text = str(inst_def.fields[0][1])
        created = getattr(mw, 'CreateComment', None)
        if created is not None:
            prev_block = bool(getattr(mw, 'collabApplyingRemoteHistory', False))
            mw.collabApplyingRemoteHistory = True
            try:
                created = mw.CreateComment(int(inst_def.objx), int(inst_def.objy), text)
            finally:
                mw.collabApplyingRemoteHistory = prev_block
        if created is not None and collab_id:
            created._collab_id = collab_id
        if created is not None:
            try:
                if hasattr(mw, '_CollabEnabled') and mw._CollabEnabled():
                    mw.CollabQueueCommentUpsert(created, is_add=True)
            except Exception:
                pass
    if created is None and hasattr(inst_def, 'createNew'):
        try:
            created = inst_def.createNew()
        except Exception:
            created = None
    try:
        from dirty import SetDirty
        SetDirty()
    except Exception:
        pass
    try:
        mw.levelOverview.update()
    except Exception:
        pass
    try:
        mw.CollabQueueMetaUpdate()
    except Exception:
        pass
    return created


def _find_path(path_id):
    for path in getattr(globals_.Area, 'paths', []):
        if int(getattr(path, '_id', -1)) == int(path_id):
            return path
    return None


def _create_path_node(path_id, node_index, node_data, loops, node_collab_id=''):
    mw = getattr(globals_, 'mainWindow', None)
    if mw is None or globals_.Area is None:
        return None
    try:
        from levelitems import Path
    except Exception:
        return None
    x, y, speed, accel, delay = node_data
    path = _find_path(path_id)
    if path is None:
        path = Path(int(path_id), mw.scene, loops=bool(loops))
        globals_.Area.paths.append(path)
    try:
        path.set_loops(bool(loops))
    except Exception:
        pass
    node = path.add_node(int(x), int(y), float(speed), float(accel), int(delay), index=int(node_index))
    try:
        if node_collab_id:
            node._collab_id = str(node_collab_id)
        else:
            cid = getattr(mw, '_CollabEnsureItemId', None)
            if cid is not None:
                cid(node)
    except Exception:
        pass
    node.positionChanged = mw.HandlePathPosChange
    try:
        mw.pathEditor.UpdatePathLength()
    except Exception:
        pass
    try:
        from dirty import SetDirty
        SetDirty()
    except Exception:
        pass
    return node


def _delete_path_node(path_id, node_index, node_collab_id=''):
    mw = getattr(globals_, 'mainWindow', None)
    if mw is None or globals_.Area is None:
        return
    path = _find_path(path_id)
    if path is None:
        return
    if node_collab_id:
        try:
            cid = str(node_collab_id)
            for idx, node in enumerate(getattr(path, '_nodes', []) or []):
                if str(getattr(node, '_collab_id', '')) == cid:
                    node_index = idx
                    break
        except Exception:
            pass
    try:
        if int(node_index) < 0 or int(node_index) >= len(path):
            return
    except Exception:
        return
    was_last = False
    try:
        was_last = path.remove_node(int(node_index))
    except Exception:
        return
    if was_last:
        try:
            globals_.Area.paths.remove(path)
        except Exception:
            pass
    try:
        mw.pathEditor.UpdatePathLength()
    except Exception:
        pass
    try:
        from dirty import SetDirty
        SetDirty()
    except Exception:
        pass


def _create_zone(zone_data):
    mw = getattr(globals_, 'mainWindow', None)
    if mw is None or globals_.Area is None or not isinstance(zone_data, dict):
        return None
    try:
        from levelitems import ZoneItem
    except Exception:
        return None
    try:
        objx = int(zone_data.get('objx', 16))
        objy = int(zone_data.get('objy', 16))
        width = int(zone_data.get('width', 408))
        height = int(zone_data.get('height', 224))
        modeldark = int(zone_data.get('modeldark', 0))
        terraindark = int(zone_data.get('terraindark', 0))
        zid = int(zone_data.get('id', 0))
        cammode = int(zone_data.get('cammode', 0))
        camzoom = int(zone_data.get('camzoom', 0))
        visibility = int(zone_data.get('visibility', 0))
        camtrack = int(zone_data.get('camtrack', 0))
        music = int(zone_data.get('music', 0))
        sfxmod = int(zone_data.get('sfxmod', 0))
    except Exception:
        return None
    bounding = [(
        int(zone_data.get('yupperbound', 0)),
        int(zone_data.get('ylowerbound', 0)),
        int(zone_data.get('yupperbound2', 0)),
        int(zone_data.get('ylowerbound2', 0)),
        0,
        int(zone_data.get('mpcamzoomadjust', 15)),
        int(zone_data.get('yupperbound3', 0)),
        int(zone_data.get('ylowerbound3', 0)),
    )]
    bgA = [(
        0,
        int(zone_data.get('XscrollA', 0)),
        int(zone_data.get('YscrollA', 0)),
        int(zone_data.get('YpositionA', 0)),
        int(zone_data.get('XpositionA', 0)),
        int(zone_data.get('bg1A', 0)),
        int(zone_data.get('bg2A', 0)),
        int(zone_data.get('bg3A', 0)),
        int(zone_data.get('ZoomA', 0)),
    )]
    bgB = [(
        0,
        int(zone_data.get('XscrollB', 0)),
        int(zone_data.get('YscrollB', 0)),
        int(zone_data.get('YpositionB', 0)),
        int(zone_data.get('XpositionB', 0)),
        int(zone_data.get('bg1B', 0)),
        int(zone_data.get('bg2B', 0)),
        int(zone_data.get('bg3B', 0)),
        int(zone_data.get('ZoomB', 0)),
    )]
    z = ZoneItem(
        objx, objy, width, height,
        modeldark, terraindark,
        zid, 0,
        cammode, camzoom, visibility,
        0, 0,
        camtrack, music, sfxmod,
        bounding, bgA, bgB,
        id_=zid,
    )
    globals_.Area.zones.append(z)
    try:
        mw.scene.addItem(z)
    except Exception:
        pass
    try:
        mw.scene.update()
        mw.levelOverview.update()
    except Exception:
        pass
    try:
        from dirty import SetDirty
        SetDirty()
    except Exception:
        pass
    try:
        mw.CollabQueueMetaUpdate()
    except Exception:
        pass
    return z


def _delete_zone(zone_data):
    mw = getattr(globals_, 'mainWindow', None)
    if mw is None or globals_.Area is None or not isinstance(zone_data, dict):
        return
    zid = zone_data.get('id', None)
    victim = None
    for z in getattr(globals_.Area, 'zones', []):
        if zid is not None and int(getattr(z, 'id', -999)) == int(zid):
            victim = z
            break
    if victim is None:
        return
    try:
        globals_.Area.zones.remove(victim)
    except Exception:
        pass
    try:
        mw.scene.removeItem(victim)
    except Exception:
        pass
    try:
        mw.scene.update()
        mw.levelOverview.update()
    except Exception:
        pass
    try:
        from dirty import SetDirty
        SetDirty()
    except Exception:
        pass
    try:
        mw.CollabQueueMetaUpdate()
    except Exception:
        pass
