/* global Vue, d3 */
(() => {
  "use strict";

  const {
    createApp,
    ref,
    computed,
    watch,
    onMounted,
    onBeforeUnmount,
    nextTick,
  } = Vue;

  const NODE_H = 58;
  const LAYER_GAP = 300;
  const ROW_GAP = 92;
  const PALETTE = ["#5eead4", "#60a5fa", "#a78bfa", "#f472b6", "#fbbf24", "#34d399"];

  const linkGenerator = d3
    .linkHorizontal()
    .x((point) => point.x)
    .y((point) => point.y);

  function clip(value, length) {
    const text = String(value ?? "");
    return text.length > length ? `${text.slice(0, length - 1)}…` : text;
  }

  function nodeWidthFor(label, id) {
    const labelWidth = clip(label, 30).length * 7.2 + 60;
    const idWidth = clip(id, 36).length * 5.6 + 56;
    return Math.max(150, Math.min(272, Math.max(labelWidth, idWidth)));
  }

  function linkPathFor(source, target) {
    const startX = source.x + source.w / 2 + 2;
    const endX = target.x - target.w / 2 - 11;
    return linkGenerator({
      source: { x: startX, y: source.y },
      target: { x: endX, y: target.y },
    });
  }

  function colorFor(node) {
    if (!node.isMain && node.depth === 0) return "#fbbf24";
    return PALETTE[node.depth % PALETTE.length];
  }

  function emptySnapshot() {
    return {
      schema: 1,
      revision: null,
      updated_at: null,
      root: "root",
      nodes: [],
      edges: [],
      stats: {
        nodes: 0,
        edges: 0,
        depth: 0,
        components: 0,
        detached_trees: 0,
        connected_nodes: 0,
        detached_nodes: 0,
      },
      meta: {},
    };
  }

  createApp({
    setup() {
      const snapshot = ref(emptySnapshot());
      const loading = ref(true);
      const connected = ref(false);
      const selectedId = ref(null);
      const hoverId = ref(null);
      const query = ref("");
      const toasts = ref([]);
      const stage = ref(null);
      const svg = ref(null);

      const nodeById = computed(() => {
        const map = new Map();
        for (const node of snapshot.value.nodes || []) map.set(node.id, node);
        return map;
      });

      const parentMap = computed(() => {
        const map = new Map();
        for (const edge of snapshot.value.edges || []) {
          if (!map.has(edge.target)) map.set(edge.target, edge.source);
        }
        return map;
      });

      const childrenMap = computed(() => {
        const map = new Map();
        for (const edge of snapshot.value.edges || []) {
          if (!map.has(edge.source)) map.set(edge.source, []);
          map.get(edge.source).push(edge.target);
        }
        return map;
      });

      const stats = computed(() => snapshot.value.stats || emptySnapshot().stats);
      const revision = computed(() => snapshot.value.revision);
      const isDemo = computed(() => Boolean(snapshot.value.meta && snapshot.value.meta.demo));
      const endpoint = computed(() => {
        const host = typeof window !== "undefined" ? window.location.host : "localhost";
        return `${host}/api/events`;
      });

      const connectionClass = computed(() => {
        if (connected.value) return "is-live";
        if (loading.value) return "is-connecting";
        return "is-offline";
      });

      const connectionLabel = computed(() => {
        if (connected.value) return "live";
        if (loading.value) return "verbinde";
        return "offline";
      });

      const connectionTitle = computed(() => {
        if (connected.value) return "Live-Verbindung zum Graph (SSE)";
        if (loading.value) return "Verbindung wird aufgebaut";
        return "Verbindung unterbrochen — neuer Versuch läuft";
      });

      const searchMatches = computed(() => {
        const needle = query.value.trim().toLowerCase();
        if (!needle) return [];
        return (snapshot.value.nodes || []).filter((node) => {
          const haystack = `${node.id}\n${node.label}\n${node.note || ""}`.toLowerCase();
          return haystack.includes(needle);
        });
      });

      const selectedNode = computed(() => {
        if (!selectedId.value) return null;
        return nodeById.value.get(selectedId.value) || null;
      });

      const selectedPath = computed(() => {
        if (!selectedId.value) return [];
        const path = [];
        const seen = new Set();
        let cursor = selectedId.value;
        while (cursor && !seen.has(cursor)) {
          seen.add(cursor);
          const node = nodeById.value.get(cursor);
          if (!node) break;
          path.push({ id: node.id, label: node.label });
          cursor = parentMap.value.get(cursor);
        }
        return path.reverse();
      });

      const selectedDepth = computed(() => Math.max(0, selectedPath.value.length - 1));

      const selectedParent = computed(() => {
        if (!selectedId.value) return null;
        const parentId = parentMap.value.get(selectedId.value);
        return parentId ? nodeById.value.get(parentId) || null : null;
      });

      const selectedChildren = computed(() => {
        if (!selectedId.value) return [];
        const ids = childrenMap.value.get(selectedId.value) || [];
        return ids.map((id) => nodeById.value.get(id)).filter(Boolean);
      });

      const selectedSubtreeSize = computed(() => {
        if (!selectedId.value) return 0;
        let count = 0;
        const seen = new Set();
        const stack = [selectedId.value];
        while (stack.length) {
          const current = stack.pop();
          if (seen.has(current)) continue;
          seen.add(current);
          count += 1;
          for (const child of childrenMap.value.get(current) || []) stack.push(child);
        }
        return count;
      });

      // ------------------------------------------------------------- D3 state
      let svgSel = null;
      let viewport = null;
      let guideLayer = null;
      let componentLayer = null;
      let linkLayer = null;
      let labelLayer = null;
      let nodeLayer = null;
      let zoomBehavior = null;
      let nodesSel = null;
      let edgesSel = null;
      let labelsSel = null;

      let positions = new Map();
      let contentBounds = null;
      let initialized = false;
      let following = true;
      let forceFit = false;
      let renderQueued = false;
      let resizeRaf = 0;
      let resizeObserver = null;
      let source = null;
      let pollingTimer = null;
      let fallbackTried = false;
      let suppressClickUntil = 0;
      let startTransform = null;
      let pointerMoved = false;
      let pulseTimer = null;
      let searchCursor = 0;
      let toastSequence = 0;
      const toastTimers = new Map();
      const pendingPulse = new Set();

      // ------------------------------------------------------------- helpers
      function labelFor(id, previousMap = null) {
        const current = nodeById.value.get(id);
        if (current) return current.label;
        const previous = previousMap ? previousMap.get(id) : null;
        return previous ? previous.label : id;
      }

      function pushToast(kind, title, text) {
        const id = ++toastSequence;
        const toast = { id, kind, title, text };
        toasts.value = [...toasts.value.slice(-3), toast];
        const timer = window.setTimeout(() => dismissToast(id), 4400);
        toastTimers.set(id, timer);
      }

      function dismissToast(id) {
        const timer = toastTimers.get(id);
        if (timer) window.clearTimeout(timer);
        toastTimers.delete(id);
        toasts.value = toasts.value.filter((toast) => toast.id !== id);
      }

      function formatDate(value) {
        if (!value) return "—";
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return String(value);
        return new Intl.DateTimeFormat("de-DE", {
          day: "2-digit",
          month: "short",
          hour: "2-digit",
          minute: "2-digit",
        }).format(date);
      }

      function selectNode(id) {
        if (id !== null && !nodeById.value.has(id)) id = null;
        selectedId.value = id;
        nextTick(applyEmphasis);
      }

      function selectAndFocus(id) {
        selectNode(id);
        nextTick(() => focusNode(id));
      }

      function focusSelected() {
        if (selectedId.value) focusNode(selectedId.value);
      }

      function clearSearch() {
        query.value = "";
        searchCursor = 0;
        nextTick(applyEmphasis);
      }

      function focusFirstMatch() {
        const matches = searchMatches.value;
        if (!matches.length) return;
        const match = matches[searchCursor % matches.length];
        searchCursor += 1;
        selectAndFocus(match.id);
      }

      // ----------------------------------------------------------- toast copy
      function onGraphChange(change, previousNodes) {
        if (!change || change.action === "noop") return;
        const label = (id) => labelFor(id, previousNodes);
        const pair = (a, b) => `${label(a)} → ${label(b)}`;

        pendingPulse.clear();
        for (const id of change.nodes_created || []) pendingPulse.add(id);
        if (change.node) pendingPulse.add(typeof change.node === "string" ? change.node : change.node.id);
        if (change.target) pendingPulse.add(change.target);

        switch (change.action) {
          case "node_added": {
            const node = change.node || {};
            pushToast(
              "add",
              "Knoten hinzugefügt",
              `${node.label || node.id || change.id}${change.parent ? ` · unter ${label(change.parent)}` : ""}`,
            );
            break;
          }
          case "edge_added": {
            const created = change.nodes_created || [];
            const title = created.length > 1 ? "Neue Knoten" : created.length === 1 ? "Neuer Knoten" : "Verbindung";
            pushToast(
              "add",
              title,
              `${pair(change.source, change.target)}${change.label ? ` · ${change.label}` : ""}`,
            );
            break;
          }
          case "parent_changed": {
            const nodeId = typeof change.node === "string" ? change.node : change.node && change.node.id;
            const child = nodeId || change.target;
            const parent = change.parent || change.source;
            const moved = change.subtree_size && change.subtree_size > 1 ? ` · ${change.subtree_size} Knoten mitverschoben` : "";
            pushToast("move", "Neu zugeordnet", `${label(child)} gehört jetzt zu ${label(parent)}${moved}`);
            forceFit = true;
            break;
          }
          case "edge_updated":
            pushToast(
              "move",
              "Kante aktualisiert",
              `${pair(change.source, change.target)}${change.label ? ` · ${change.label}` : ""}`,
            );
            break;
          case "edge_removed":
            pushToast(
              "remove",
              "Verbindung gelöst",
              `${pair(change.source, change.target)} entfernt · ${change.detached_nodes || 0} Knoten bleiben erhalten`,
            );
            forceFit = true;
            break;
          case "node_updated": {
            const fieldNames = { label: "Label", note: "Notiz" };
            const fields = (change.fields || []).map((field) => fieldNames[field] || field);
            pushToast(
              "move",
              "Knoten aktualisiert",
              `${label(change.node && change.node.id)}${fields.length ? ` · ${fields.join(", ")}` : ""}`,
            );
            break;
          }
          case "node_removed":
            pushToast(
              "remove",
              "Knoten entfernt",
              change.mode === "cascade"
                ? `${label(change.node)} und ${Math.max(0, (change.nodes_removed || 1) - 1)} weitere Knoten`
                : `${label(change.node)} · Kinder neu angehängt`,
            );
            forceFit = true;
            break;
          case "graph_reset":
            pushToast(
              "reset",
              "Graph zurückgesetzt",
              `${change.nodes_removed || 0} Knoten entfernt · Root bleibt`,
            );
            forceFit = true;
            break;
          default:
            if (change.message) pushToast("add", "Graph aktualisiert", change.message);
        }
      }

      // --------------------------------------------------------------- data
      function applySnapshot(data) {
        if (!data || !Array.isArray(data.nodes)) return;
        const first = loading.value;
        const previousNodes = nodeById.value;
        snapshot.value = data;
        loading.value = false;
        connected.value = true;
        if (!first && data.change) onGraphChange(data.change, previousNodes);
        if (data.change && data.change.action === "graph_reset") forceFit = true;
        if (selectedId.value && !nodeById.value.has(selectedId.value)) selectedId.value = null;
        if (query.value.trim()) searchCursor = 0;
        scheduleRender();
      }

      function scheduleRender() {
        if (renderQueued) return;
        renderQueued = true;
        window.requestAnimationFrame(() => {
          renderQueued = false;
          renderGraph();
        });
      }

      // ------------------------------------------------------------- layout
      function renderGraph() {
        if (!svgSel) return;
        const data = snapshot.value;
        const nodes = data.nodes || [];
        const edges = data.edges || [];

        if (!nodes.length) {
          guideLayer.selectAll("*").remove();
          componentLayer.selectAll("*").remove();
          linkLayer.selectAll("*").remove();
          labelLayer.selectAll("*").remove();
          nodeLayer.selectAll("*").remove();
          positions = new Map();
          nodesSel = null;
          edgesSel = null;
          labelsSel = null;
          return;
        }

        const byId = new Map(nodes.map((node) => [node.id, node]));
        const rootId = data.root && byId.has(data.root) ? data.root : nodes[0].id;
        const orderById = new Map(nodes.map((node, index) => [node.id, index]));

        const parent = new Map();
        const children = new Map();
        for (const edge of edges) {
          if (!byId.has(edge.source) || !byId.has(edge.target)) continue;
          if (parent.has(edge.target)) continue;
          parent.set(edge.target, edge.source);
          if (!children.has(edge.source)) children.set(edge.source, []);
          children.get(edge.source).push(edge.target);
        }

        const placed = new Set();
        function buildTree(id) {
          if (placed.has(id)) return null;
          const node = byId.get(id);
          if (!node) return null;
          placed.add(id);
          const kids = [];
          for (const childId of children.get(id) || []) {
            const child = buildTree(childId);
            if (child) kids.push(child);
          }
          return {
            id,
            label: node.label,
            note: node.note || "",
            created_at: node.created_at,
            order: orderById.get(id) ?? 0,
            children: kids,
          };
        }

        const treeLayout = d3.tree().nodeSize([ROW_GAP, LAYER_GAP]);
        function layoutTree(treeData) {
          const hierarchy = d3.hierarchy(treeData, (node) => node.children);
          hierarchy.sort((a, b) => (a.data.order ?? 0) - (b.data.order ?? 0));
          treeLayout(hierarchy);
          return hierarchy;
        }

        const mainData = buildTree(rootId);
        if (!mainData) return;
        const mainHierarchy = layoutTree(mainData);
        const previousPositions = positions;
        const newPositions = new Map();
        const layoutNodes = [];

        function addComponent(hierarchy, offsetY, componentRoot, isMain) {
          const componentNodes = [];
          hierarchy.each((node) => {
            const width = nodeWidthFor(node.data.label, node.data.id);
            const item = {
              id: node.data.id,
              label: node.data.label,
              note: node.data.note,
              parentId: parent.get(node.data.id) || null,
              depth: node.depth,
              x: node.y,
              y: node.x + offsetY,
              w: width,
              isMain,
              componentRoot,
              order: node.data.order,
            };
            newPositions.set(item.id, item);
            layoutNodes.push(item);
            componentNodes.push(item);
          });
          return componentNodes;
        }

        const mainOffsetY = -mainHierarchy.x;
        const mainNodes = addComponent(mainHierarchy, mainOffsetY, rootId, true);
        const detachedComponents = [];
        const detachedRoots = nodes
          .filter((node) => node.id !== rootId && !parent.has(node.id))
          .sort((a, b) => (orderById.get(a.id) ?? 0) - (orderById.get(b.id) ?? 0));

        let cursor = Math.max(...mainNodes.map((node) => node.y + NODE_H / 2)) + 150;
        for (const detachedRoot of detachedRoots) {
          const treeData = buildTree(detachedRoot.id);
          if (!treeData) continue;
          const hierarchy = layoutTree(treeData);
          const descendants = hierarchy.descendants();
          const minBreadth = d3.min(descendants, (node) => node.x) ?? hierarchy.x;
          const maxBreadth = d3.max(descendants, (node) => node.x) ?? hierarchy.x;
          const offsetY = cursor + NODE_H / 2 - minBreadth;
          const componentNodes = addComponent(hierarchy, offsetY, detachedRoot.id, false);
          const top = cursor;
          const bottom = offsetY + maxBreadth + NODE_H / 2;
          const minCardX = Math.min(...componentNodes.map((node) => node.x - node.w / 2));
          const maxCardX = Math.max(...componentNodes.map((node) => node.x + node.w / 2));
          detachedComponents.push({
            id: detachedRoot.id,
            label: byId.get(detachedRoot.id).label,
            count: componentNodes.length,
            x: minCardX - 34,
            y: top - 52,
            w: maxCardX - minCardX + 68,
            h: bottom - top + 78,
          });
          cursor = bottom + 118;
        }

        positions = newPositions;
        const allNodes = layoutNodes;
        const maxDepth = d3.max(allNodes, (node) => node.depth) ?? 0;

        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        for (const node of allNodes) {
          minX = Math.min(minX, node.x - node.w / 2);
          maxX = Math.max(maxX, node.x + node.w / 2);
          minY = Math.min(minY, node.y - NODE_H / 2);
          maxY = Math.max(maxY, node.y + NODE_H / 2);
        }
        for (const component of detachedComponents) {
          minX = Math.min(minX, component.x);
          minY = Math.min(minY, component.y);
          maxX = Math.max(maxX, component.x + component.w);
          maxY = Math.max(maxY, component.y + component.h);
        }
        contentBounds = {
          x: minX - 24,
          y: minY - 34,
          w: maxX - minX + 48,
          h: maxY - minY + 68,
        };

        // Layer guides ------------------------------------------------------
        const guideData = [];
        if (allNodes.length > 1) {
          for (let depth = 0; depth <= maxDepth; depth += 1) {
            guideData.push({ depth, x: depth * LAYER_GAP });
          }
        }
        const guides = guideLayer.selectAll("g.guide").data(guideData, (item) => item.depth);
        const guideEnter = guides.enter().append("g").attr("class", "guide");
        guideEnter.append("line").attr("class", "guide-line");
        guideEnter.append("text").attr("class", "guide-label");
        const guideMerged = guideEnter.merge(guides);
        guideMerged
          .select("line")
          .attr("x1", (item) => item.x)
          .attr("x2", (item) => item.x)
          .attr("y1", contentBounds.y + 22)
          .attr("y2", contentBounds.y + contentBounds.h - 22);
        guideMerged
          .select("text")
          .attr("x", (item) => item.x + 8)
          .attr("y", contentBounds.y + 15)
          .text((item) => `L${item.depth}`);
        guides.exit().remove();

        // Detached component frames ----------------------------------------
        const componentSel = componentLayer
          .selectAll("g.detached-component")
          .data(detachedComponents, (item) => item.id);
        const componentEnter = componentSel.enter().append("g").attr("class", "detached-component");
        componentEnter.append("rect").attr("class", "detached-box").attr("rx", 17);
        componentEnter.append("text").attr("class", "detached-label");
        componentEnter.append("text").attr("class", "detached-meta");
        const componentMerged = componentEnter.merge(componentSel);
        componentMerged
          .select("rect")
          .attr("x", (item) => item.x)
          .attr("y", (item) => item.y)
          .attr("width", (item) => item.w)
          .attr("height", (item) => item.h);
        componentMerged
          .select(".detached-label")
          .attr("x", (item) => item.x + 17)
          .attr("y", (item) => item.y + 25)
          .text("LOSGELÖST");
        componentMerged
          .select(".detached-meta")
          .attr("x", (item) => item.x + 17)
          .attr("y", (item) => item.y + 40)
          .text((item) => `${item.count} Knoten · ${clip(item.label, 38)}`);
        componentSel.exit().remove();

        // Edges -------------------------------------------------------------
        const linkData = [];
        for (const edge of edges) {
          const sourcePos = newPositions.get(edge.source);
          const targetPos = newPositions.get(edge.target);
          if (!sourcePos || !targetPos) continue;
          linkData.push({
            key: `${edge.source}\u0000${edge.target}`,
            source: edge.source,
            target: edge.target,
            label: edge.label || "",
            s: sourcePos,
            t: targetPos,
          });
        }

        const edgeJoin = linkLayer.selectAll("path.edge").data(linkData, (item) => item.key);
        const edgeEnter = edgeJoin
          .enter()
          .append("path")
          .attr("class", "edge")
          .attr("marker-end", "url(#vg-arrow)")
          .attr("opacity", 0)
          .attr("d", (item) => linkPathFor(item.s, item.t));
        const edgeMerged = edgeEnter.merge(edgeJoin);
        edgeMerged
          .interrupt("flow")
          .transition("flow")
          .duration(560)
          .ease(d3.easeCubicOut)
          .attr("opacity", 1)
          .attr("d", (item) => linkPathFor(item.s, item.t));
        edgeJoin
          .exit()
          .interrupt("flow")
          .transition("flow")
          .duration(230)
          .attr("opacity", 0)
          .remove();
        edgesSel = edgeMerged;

        const labelData = linkData.filter((item) => item.label);
        const labelJoin = labelLayer
          .selectAll("g.edge-label")
          .data(labelData, (item) => item.key);
        const labelEnter = labelJoin.enter().append("g").attr("class", "edge-label");
        labelEnter.append("text").attr("text-anchor", "middle");
        labelJoin
          .exit()
          .transition("fade")
          .duration(180)
          .attr("opacity", 0)
          .remove();
        const labelMerged = labelEnter.merge(labelJoin);
        labelMerged
          .interrupt("flow")
          .attr("opacity", 1)
          .attr("transform", (item) => {
            const x = (item.s.x + item.s.w / 2 + item.t.x - item.t.w / 2) / 2;
            const y = (item.s.y + item.t.y) / 2 - 8;
            return `translate(${x},${y})`;
          });
        labelMerged
          .select("text")
          .text((item) => clip(item.label, 22));
        labelsSel = labelMerged;

        // Nodes -------------------------------------------------------------
        const isFirstPaint = !initialized && !loading.value;
        const nodeJoin = nodeLayer.selectAll("g.node").data(allNodes, (item) => item.id);
        const nodeEnter = nodeJoin
          .enter()
          .append("g")
          .attr("class", "node")
          .attr("tabindex", 0)
          .attr("role", "button");
        nodeEnter.append("rect").attr("class", "node-card").attr("rx", 13);
        nodeEnter.append("rect").attr("class", "node-accent").attr("rx", 1.5);
        nodeEnter.append("text").attr("class", "node-label");
        nodeEnter.append("text").attr("class", "node-id");
        nodeEnter.append("title");

        function enterPosition(node) {
          const parentPos = node.parentId ? previousPositions.get(node.parentId) : null;
          const ownPos = previousPositions.get(node.id);
          if (parentPos) return parentPos;
          if (ownPos) return ownPos;
          return { x: node.x - 36, y: node.y };
        }

        nodeEnter
          .attr("transform", (node) => {
            const pos = enterPosition(node);
            return `translate(${pos.x},${pos.y})`;
          })
          .attr("opacity", 0);

        const nodeMerged = nodeEnter.merge(nodeJoin);
        nodeMerged
          .classed("is-root", (node) => node.id === rootId)
          .classed("is-main", (node) => node.isMain)
          .attr("aria-label", (node) => `${node.label}, ${node.id}, Tiefe ${node.depth}`);

        nodeMerged
          .select(".node-card")
          .attr("x", (node) => -node.w / 2)
          .attr("y", -NODE_H / 2)
          .attr("width", (node) => node.w)
          .attr("height", NODE_H);

        nodeMerged
          .select(".node-accent")
          .attr("x", (node) => -node.w / 2 + 1)
          .attr("y", -NODE_H / 2 + 9)
          .attr("width", 3)
          .attr("height", NODE_H - 18)
          .attr("fill", (node) => colorFor(node));

        nodeMerged
          .select(".node-label")
          .attr("x", (node) => -node.w / 2 + 16)
          .attr("y", -1.5)
          .text((node) => clip(node.label, 30));

        nodeMerged
          .select(".node-id")
          .attr("x", (node) => -node.w / 2 + 16)
          .attr("y", 14)
          .text((node) => clip(node.id, 36));

        nodeMerged
          .select("title")
          .text((node) =>
            [node.label, node.id, node.note, `Tiefe ${node.depth}`]
              .filter(Boolean)
              .join("\n"),
          );

        nodeJoin
          .exit()
          .interrupt("move")
          .transition("move")
          .duration(220)
          .attr("opacity", 0)
          .remove();

        nodeMerged
          .interrupt("move")
          .transition("move")
          .duration(isFirstPaint ? 680 : 560)
          .delay((node) => (isFirstPaint ? Math.min(420, node.depth * 70) : 0))
          .ease(d3.easeCubicOut)
          .attrTween("transform", (node) => {
            const parentPos = node.parentId
              ? previousPositions.get(node.parentId) || newPositions.get(node.parentId)
              : null;
            const start = previousPositions.get(node.id) || parentPos || enterPosition(node);
            const ix = d3.interpolateNumber(start.x, node.x);
            const iy = d3.interpolateNumber(start.y, node.y);
            return (t) => `translate(${ix(t)},${iy(t)})`;
          })
          .attr("opacity", 1);

        nodeMerged
          .on("click", (event, node) => {
            event.stopPropagation();
            if (Date.now() < suppressClickUntil) return;
            selectNode(node.id);
          })
          .on("mouseenter", (event, node) => {
            hoverId.value = node.id;
            applyEmphasis();
          })
          .on("mouseleave", () => {
            hoverId.value = null;
            applyEmphasis();
          })
          .on("keydown", (event, node) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              selectNode(node.id);
            }
          });

        nodesSel = nodeMerged;

        if (pendingPulse.size) {
          nodeMerged.classed("is-new", (node) => pendingPulse.has(node.id));
          pendingPulse.clear();
          window.clearTimeout(pulseTimer);
          pulseTimer = window.setTimeout(() => {
            if (nodeLayer) nodeLayer.selectAll("g.node").classed("is-new", false);
          }, 2200);
        }

        applyEmphasis();

        if (isFirstPaint) {
          initialized = true;
          window.requestAnimationFrame(() => fitView(false, true));
        } else if (forceFit) {
          forceFit = false;
          if (following) window.requestAnimationFrame(() => fitView(true, false));
        } else if (initialized && following) {
          ensureVisible();
        }
      }

      // -------------------------------------------------------------- camera
      function fitView(animate = true, enableFollow = true) {
        if (!svgSel || !contentBounds) return;
        const width = svg.value.clientWidth || stage.value.clientWidth;
        const height = svg.value.clientHeight || stage.value.clientHeight;
        if (!width || !height) return;
        const padding = Math.max(36, Math.min(88, Math.min(width, height) * 0.09));
        const wide = window.innerWidth > 860;
        const panelSpace = wide && selectedId.value ? 346 : 0;
        const availableWidth = Math.max(240, width - panelSpace);
        const rawScale = Math.min(
          (availableWidth - padding * 2) / Math.max(1, contentBounds.w),
          (height - padding * 2) / Math.max(1, contentBounds.h),
        );
        const maxScale = (snapshot.value.nodes || []).length <= 6 ? 1.3 : 1.12;
        const scale = Math.max(0.08, Math.min(maxScale, rawScale || 1));
        const transform = d3.zoomIdentity
          .translate(
            availableWidth / 2 - scale * (contentBounds.x + contentBounds.w / 2),
            height / 2 - scale * (contentBounds.y + contentBounds.h / 2),
          )
          .scale(scale);

        if (animate) {
          svgSel
            .transition("fit")
            .duration(620)
            .ease(d3.easeCubicOut)
            .call(zoomBehavior.transform, transform);
        } else {
          svgSel.call(zoomBehavior.transform, transform);
        }
        if (enableFollow) following = true;
      }

      function ensureVisible() {
        if (!following || !contentBounds || !initialized) return;
        const width = svg.value.clientWidth || 0;
        const height = svg.value.clientHeight || 0;
        if (!width || !height) return;
        const current = d3.zoomTransform(svgSel.node());
        const x0 = current.applyX(contentBounds.x);
        const y0 = current.applyY(contentBounds.y);
        const x1 = current.applyX(contentBounds.x + contentBounds.w);
        const y1 = current.applyY(contentBounds.y + contentBounds.h);
        const pad = 26;
        if (x0 < pad || y0 < pad || x1 > width - pad || y1 > height - pad) {
          fitView(true, false);
        }
      }

      function focusNode(id) {
        if (!svgSel) return;
        const pos = positions.get(id);
        if (!pos) return;
        const width = svg.value.clientWidth || stage.value.clientWidth;
        const height = svg.value.clientHeight || stage.value.clientHeight;
        const wide = window.innerWidth > 860;
        const panelOpen = wide && Boolean(selectedId.value);
        const targetX = wide ? (width - (panelOpen ? 346 : 0)) / 2 : width / 2;
        const targetY = wide ? height / 2 : height * 0.38;
        const current = d3.zoomTransform(svgSel.node());
        const scale = Math.min(1.25, Math.max(current.k, 1));
        const transform = d3.zoomIdentity
          .translate(targetX - scale * pos.x, targetY - scale * pos.y)
          .scale(scale);
        svgSel
          .transition("focus")
          .duration(620)
          .ease(d3.easeCubicOut)
          .call(zoomBehavior.transform, transform);
        following = false;
      }

      function zoomBy(factor) {
        if (!svgSel) return;
        svgSel.transition("zoom").duration(260).call(zoomBehavior.scaleBy, factor);
        following = false;
      }

      function zoomIn() {
        zoomBy(1.3);
      }

      function zoomOut() {
        zoomBy(1 / 1.3);
      }

      // ------------------------------------------------------------ emphasis
      function applyEmphasis() {
        if (!nodesSel || !edgesSel) return;
        const active = hoverId.value || selectedId.value;
        let focusSet = null;
        if (active && nodeById.value.has(active)) {
          focusSet = new Set([active]);
          let cursor = parentMap.value.get(active);
          while (cursor && !focusSet.has(cursor)) {
            focusSet.add(cursor);
            cursor = parentMap.value.get(cursor);
          }
          const stack = [active];
          while (stack.length) {
            const current = stack.pop();
            for (const child of childrenMap.value.get(current) || []) {
              if (!focusSet.has(child)) {
                focusSet.add(child);
                stack.push(child);
              }
            }
          }
        }

        const needle = query.value.trim().toLowerCase();
        let matchSet = null;
        if (needle) {
          const matches = new Set(searchMatches.value.map((node) => node.id));
          if (matches.size) matchSet = matches;
        }

        const isDimNode = (node) => {
          if (focusSet) return !focusSet.has(node.id) && !(matchSet && matchSet.has(node.id));
          if (matchSet) return !matchSet.has(node.id);
          return false;
        };

        nodesSel
          .classed("is-selected", (node) => node.id === selectedId.value)
          .classed("is-focus", (node) => Boolean(focusSet && focusSet.has(node.id)))
          .classed("is-match", (node) => Boolean(matchSet && matchSet.has(node.id)))
          .classed("is-dim", isDimNode);

        const edgeIsFocused = (edge) =>
          Boolean(focusSet && focusSet.has(edge.source) && focusSet.has(edge.target));
        const edgeIsDim = (edge) => {
          if (focusSet) return !edgeIsFocused(edge);
          if (matchSet) return !(matchSet.has(edge.source) || matchSet.has(edge.target));
          return false;
        };

        edgesSel
          .classed("is-related", edgeIsFocused)
          .classed("is-dim", edgeIsDim)
          .attr("marker-end", (edge) =>
            edgeIsFocused(edge) ? "url(#vg-arrow-bright)" : "url(#vg-arrow)",
          );

        if (labelsSel) {
          labelsSel.classed("is-dim", (edge) => {
            if (focusSet) return !edgeIsFocused(edge);
            if (matchSet) return !(matchSet.has(edge.source) || matchSet.has(edge.target));
            return false;
          });
        }
      }

      // ---------------------------------------------------------------- init
      function initSvg() {
        svgSel = d3.select(svg.value);
        const defs = svgSel.append("defs");
        const marker = (id, color) => {
          const element = defs
            .append("marker")
            .attr("id", id)
            .attr("viewBox", "0 0 10 10")
            .attr("refX", 9)
            .attr("refY", 5)
            .attr("markerWidth", 7)
            .attr("markerHeight", 7)
            .attr("orient", "auto-start-reverse");
          element
            .append("path")
            .attr("d", "M 0 0 L 10 5 L 0 10 z")
            .attr("fill", color);
        };
        marker("vg-arrow", "#73849c");
        marker("vg-arrow-bright", "#5eead4");

        viewport = svgSel.append("g").attr("class", "viewport");
        guideLayer = viewport.append("g").attr("class", "layer-guides");
        componentLayer = viewport.append("g").attr("class", "layer-components");
        linkLayer = viewport.append("g").attr("class", "layer-edges");
        labelLayer = viewport.append("g").attr("class", "layer-labels");
        nodeLayer = viewport.append("g").attr("class", "layer-nodes");

        svgSel.on("click", () => {
          if (Date.now() < suppressClickUntil) return;
          if (selectedId.value) selectNode(null);
        });

        zoomBehavior = d3
          .zoom()
          .scaleExtent([0.08, 2.6])
          .on("start", () => {
            startTransform = d3.zoomTransform(svgSel.node());
            pointerMoved = false;
          })
          .on("zoom", (event) => {
            viewport.attr("transform", event.transform);
            if (event.sourceEvent) {
              following = false;
              if (
                startTransform &&
                (Math.abs(event.transform.x - startTransform.x) > 2 ||
                  Math.abs(event.transform.y - startTransform.y) > 2 ||
                  Math.abs(event.transform.k - startTransform.k) > 0.001)
              ) {
                pointerMoved = true;
              }
            }
          })
          .on("end", () => {
            if (pointerMoved) suppressClickUntil = Date.now() + 260;
            startTransform = null;
            pointerMoved = false;
          });

        svgSel.call(zoomBehavior).on("dblclick.zoom", null);
        resizeSvg();
      }

      function resizeSvg() {
        if (!svgSel || !stage.value) return;
        const width = stage.value.clientWidth;
        const height = stage.value.clientHeight;
        if (!width || !height) return;
        svgSel
          .attr("width", width)
          .attr("height", height)
          .attr("viewBox", `0 0 ${width} ${height}`);
        if (initialized && following) fitView(false, false);
      }

      function scheduleResize() {
        if (resizeRaf) return;
        resizeRaf = window.requestAnimationFrame(() => {
          resizeRaf = 0;
          resizeSvg();
        });
      }

      // ----------------------------------------------------------------- SSE
      async function fetchSnapshot() {
        try {
          const response = await fetch("/api/graph", { cache: "no-store" });
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          applySnapshot(await response.json());
        } catch (error) {
          connected.value = false;
          if (loading.value) {
            window.setTimeout(fetchSnapshot, 2500);
          }
        }
      }

      function startPolling() {
        const tick = async () => {
          await fetchSnapshot();
          pollingTimer = window.setTimeout(tick, 3000);
        };
        tick();
      }

      function connect() {
        if (!("EventSource" in window)) {
          startPolling();
          return;
        }
        source = new EventSource("/api/events");
        source.addEventListener("graph", (event) => {
          try {
            applySnapshot(JSON.parse(event.data));
          } catch (error) {
            console.warn("VibeGraph: invalid SSE payload", error);
          }
        });
        source.onopen = () => {
          connected.value = true;
        };
        source.onerror = () => {
          connected.value = false;
          if (loading.value && !fallbackTried) {
            fallbackTried = true;
            fetchSnapshot();
          }
        };
      }

      // ------------------------------------------------------------ keyboard
      function handleKeydown(event) {
        const target = event.target;
        const typing =
          target &&
          (target.tagName === "INPUT" ||
            target.tagName === "TEXTAREA" ||
            target.isContentEditable);
        if (typing) return;

        if (event.key === "Escape") {
          if (query.value) clearSearch();
          else selectNode(null);
        } else if (event.key === "+" || event.key === "=") {
          zoomIn();
        } else if (event.key === "-") {
          zoomOut();
        } else if (event.key === "0") {
          fitView();
        }
      }

      watch(selectedId, () => nextTick(applyEmphasis));
      watch(query, () => {
        searchCursor = 0;
        nextTick(applyEmphasis);
      });

      onMounted(() => {
        initSvg();
        window.addEventListener("keydown", handleKeydown);
        window.addEventListener("resize", scheduleResize);
        resizeObserver = new ResizeObserver(scheduleResize);
        if (stage.value) resizeObserver.observe(stage.value);
        renderGraph();
        connect();
      });

      onBeforeUnmount(() => {
        if (source) source.close();
        if (pollingTimer) window.clearTimeout(pollingTimer);
        if (pulseTimer) window.clearTimeout(pulseTimer);
        for (const timer of toastTimers.values()) window.clearTimeout(timer);
        toastTimers.clear();
        if (resizeObserver) resizeObserver.disconnect();
        if (resizeRaf) window.cancelAnimationFrame(resizeRaf);
        window.removeEventListener("keydown", handleKeydown);
        window.removeEventListener("resize", scheduleResize);
      });

      return {
        stage,
        svg,
        loading,
        query,
        toasts,
        stats,
        revision,
        isDemo,
        endpoint,
        connectionClass,
        connectionLabel,
        connectionTitle,
        searchMatches,
        selectedNode,
        selectedPath,
        selectedDepth,
        selectedParent,
        selectedChildren,
        selectedSubtreeSize,
        selectNode,
        selectAndFocus,
        focusSelected,
        clearSearch,
        focusFirstMatch,
        dismissToast,
        formatDate,
        zoomIn,
        zoomOut,
        fitView,
      };
    },
  }).mount("#app");
})();
