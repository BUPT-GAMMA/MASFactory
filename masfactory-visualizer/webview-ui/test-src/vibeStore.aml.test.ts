import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DOMParser } from '@xmldom/xmldom';
import { createPinia, setActivePinia } from 'pinia';
import { useVibeStore } from '../src/stores/vibeStore';
import { validateGraphDesign } from '../src/utils/vibeValidation';
import {
  AML_ACTIVE_GRAPH_ID_KEY,
  parseAmlGraphDesign,
  serializeAmlExternalGraphEdits,
  serializeAmlGraphDesign
} from '../src/utils/amlGraphDesign';

(globalThis as any).DOMParser = DOMParser;
(globalThis as any).window = {
  addEventListener() {},
  removeEventListener() {}
};

const amlSource = `<?xml version="1.0" encoding="UTF-8"?>
<aml version="0.2">
  <agents>
    <agent id="writer" instructions="write" />
  </agents>
  <graph id="root" kind="root">
    <attributes>
      <attribute name="topic" value="aml" />
    </attributes>
    <nodes>
      <agent id="draft" ref="#writer" />
      <graph id="phase" implementation="python:demo.workflow.Phase" />
    </nodes>
    <edges>
      <edge from="entry" to="draft" />
      <edge from="draft" to="phase" />
      <edge from="phase" to="exit" />
    </edges>
  </graph>
  <graph id="definition_to_keep">
    <nodes>
      <agent id="nested" ref="#writer" />
    </nodes>
    <edges>
      <edge from="entry" to="nested" />
      <edge from="nested" to="exit" />
    </edges>
  </graph>
</aml>`;

const implementationGraphs = {
  'python:demo.workflow.Phase': {
    nodes: ['entry', 'review', 'exit'],
    nodeTypes: { review: 'Action' },
    edges: [
      { from: 'entry', to: 'review', keysDetails: { draft: 'Draft text' } },
      { from: 'review', to: 'exit' }
    ]
  }
};

test('AML serializer filters derived implementation preview and preserves outer content', () => {
  const parsed = parseAmlGraphDesign(amlSource, { implementationGraphs }).graph;

  assert.ok(parsed.Nodes.some((node: any) => node.__aml_from_implementation));
  assert.ok(parsed.Edges.some((edge: any) => edge.__aml_from_implementation));

  const draft = parsed.Nodes.find((node) => node.name === 'draft');
  assert.ok(draft);
  draft!.label = 'Draft';
  parsed.Edges.push({ from: 'draft', to: 'exit', keys: { final: 'Final text' } });

  const saved = serializeAmlGraphDesign(amlSource, parsed);

  assert.match(saved, /<graph id="definition_to_keep">/);
  assert.match(saved, /<agent id="nested" ref="#writer" \/>/);
  assert.match(saved, /<agent id="draft" label="Draft" ref="#writer" \/>/);
  assert.match(saved, /<edge from="draft" to="exit">/);
  assert.doesNotMatch(saved, /phase__review/);
  assert.doesNotMatch(saved, /Draft text/);
});

test('AML implementation preview refresh preserves dirty source edits', () => {
  setActivePinia(createPinia());
  const vibe = useVibeStore();
  const uri = 'file:///workspace/main.aml';

  assert.equal(
    vibe.ingestDocument({
      uri,
      fileName: 'main.aml',
      languageId: 'aml',
      text: amlSource
    }),
    true
  );

  vibe.updateNodeSpec(uri, 'draft', {
    name: 'draft',
    type: 'Agent',
    label: 'Dirty draft',
    agent: 'writer'
  });

  assert.equal(vibe.docs[uri].dirty, true);
  assert.equal(vibe.docs[uri].dirtyGraph?.Nodes.some((node: any) => node.label === 'Dirty draft'), true);

  assert.equal(
    vibe.ingestDocument({
      uri,
      fileName: 'main.aml',
      languageId: 'aml',
      text: amlSource,
      implementationGraphs
    }),
    true
  );

  const doc = vibe.docs[uri];
  assert.equal(doc.dirty, true);
  assert.equal(doc.dirtyGraph?.Nodes.some((node: any) => node.label === 'Dirty draft'), true);
  assert.equal(doc.dirtyGraph?.Nodes.some((node: any) => node.name === 'phase__review'), true);
  assert.equal(
    doc.dirtyGraph?.Edges.some(
      (edge: any) => edge.__aml_from_implementation && edge.from === 'phase.entry' && edge.to === 'phase__review'
    ),
    true
  );
});

test('AML implementation preview nodes do not trigger source Agent validation warnings', () => {
  const parsed = parseAmlGraphDesign(amlSource, { implementationGraphs }).graph;
  const validation = validateGraphDesign(parsed);

  assert.equal(
    validation.issues.some((issue: any) => String(issue.message || '').includes('phase__review') && String(issue.message || '').includes('agent')),
    false
  );
});

test('AML graph refs inherit implementation previews from definitions', () => {
  const source = `<?xml version="1.0" encoding="UTF-8"?>
<aml version="0.2">
  <definitions>
    <graphs>
      <graph id="phase_definition" implementation="python:demo.workflow.Phase" />
    </graphs>
  </definitions>
  <graph id="root" kind="root">
    <nodes>
      <graph id="phase" ref="#phase_definition" />
    </nodes>
    <edges>
      <edge from="entry" to="phase" />
      <edge from="phase" to="exit" />
    </edges>
  </graph>
</aml>`;

  const parsed = parseAmlGraphDesign(source, { implementationGraphs }).graph;
  const phase = parsed.Nodes.find((node: any) => node.name === 'phase') as any;

  assert.equal(phase?.implementation, 'python:demo.workflow.Phase');
  assert.equal(phase?.__aml_inherited_implementation, true);
  assert.equal(parsed.Nodes.some((node: any) => node.name === 'phase__review' && node.__aml_from_implementation), true);
  assert.equal(
    parsed.Edges.some(
      (edge: any) => edge.__aml_from_implementation && edge.from === 'phase.entry' && edge.to === 'phase__review'
    ),
    true
  );
});

test('AML implementation preview refresh does not reattach deleted dirty containers', () => {
  setActivePinia(createPinia());
  const vibe = useVibeStore();
  const uri = 'file:///workspace/main.aml';

  vibe.ingestDocument({
    uri,
    fileName: 'main.aml',
    languageId: 'aml',
    text: amlSource
  });
  vibe.deleteNode(uri, 'phase');

  assert.equal(vibe.docs[uri].dirty, true);

  vibe.ingestDocument({
    uri,
    fileName: 'main.aml',
    languageId: 'aml',
    text: amlSource,
    implementationGraphs
  });

  const doc = vibe.docs[uri];
  assert.equal(doc.dirty, true);
  assert.equal(doc.dirtyGraph?.Nodes.some((node: any) => node.name === 'phase'), false);
  assert.equal(doc.dirtyGraph?.Nodes.some((node: any) => node.name === 'phase__review'), false);
  assert.equal(doc.dirtyGraph?.Edges.some((edge: any) => edge.__aml_from_implementation), false);
});

test('AML implementation preview survives base document refresh without implementation payload', () => {
  setActivePinia(createPinia());
  const vibe = useVibeStore();
  const uri = 'file:///workspace/main.aml';

  vibe.ingestDocument({
    uri,
    fileName: 'main.aml',
    languageId: 'aml',
    text: amlSource,
    implementationGraphs
  });

  assert.equal(vibe.docs[uri].graph?.Nodes.some((node: any) => node.name === 'phase__review'), true);

  vibe.ingestDocument({
    uri,
    fileName: 'main.aml',
    languageId: 'aml',
    text: amlSource
  });

  assert.equal(vibe.docs[uri].graph?.Nodes.some((node: any) => node.name === 'phase__review'), true);
  assert.equal(
    vibe.docs[uri].graph?.Edges.some((edge: any) => edge.__aml_from_implementation && edge.from === 'phase.entry'),
    true
  );
});

test('AML imported graph refs expand as external editable source and serialize only source refs in parent', () => {
  const source = `<?xml version="1.0" encoding="UTF-8"?>
<aml version="0.2">
  <imports>
    <import alias="simple" src="./simple.aml" />
  </imports>
  <graph id="root" kind="root">
    <nodes>
      <graph id="phase" ref="simple::phase" />
    </nodes>
    <edges>
      <edge from="entry" to="phase" />
      <edge from="phase" to="exit" />
    </edges>
  </graph>
</aml>`;
  const imported = `<aml version="0.2">
  <agents>
    <agent id="writer" instructions="write imported" />
  </agents>
  <graph id="phase">
    <nodes>
      <agent id="inner" ref="#writer" />
    </nodes>
    <edges>
      <edge from="entry" to="inner" />
      <edge from="inner" to="exit" />
    </edges>
  </graph>
</aml>`;

  const parsed = parseAmlGraphDesign(source, {
    importedDocuments: {
      simple: {
        alias: 'simple',
        filePath: '/workspace/simple.aml',
        text: imported
      }
    }
  }).graph;

  const phase = parsed.Nodes.find((node) => node.name === 'phase') as any;
  const inner = parsed.Nodes.find((node) => node.name === 'phase__inner') as any;
  assert.equal(phase?.__aml_ref_filePath, '/workspace/simple.aml');
  assert.equal(phase?.__aml_ref_graphId, 'phase');
  assert.equal(inner?.__aml_from_ref, true);
  assert.equal(inner?.__aml_external_parent, 'phase');
  assert.equal(inner?.__aml_external_local_name, 'inner');
  assert.equal(inner?.parent, 'phase');
  assert.equal(parsed.Edges.some((edge: any) => edge.__aml_from_ref && edge.from === 'phase.entry'), true);

  const saved = serializeAmlGraphDesign(source, parsed);
  assert.match(saved, /<graph id="phase" ref="#simple::phase" \/>/);
  assert.doesNotMatch(saved, /phase__inner/);
  assert.doesNotMatch(saved, /write imported/);
});

test('AML import preview survives base document refresh without importedDocuments payload', () => {
  setActivePinia(createPinia());
  const vibe = useVibeStore();
  const uri = 'file:///workspace/main.aml';
  const source = `<?xml version="1.0" encoding="UTF-8"?>
<aml version="0.2">
  <imports>
    <import alias="simple" src="./simple.aml" />
  </imports>
  <graph id="root" kind="root">
    <nodes>
      <graph id="phase" ref="simple::phase" />
    </nodes>
    <edges>
      <edge from="entry" to="phase" />
      <edge from="phase" to="exit" />
    </edges>
  </graph>
</aml>`;
  const imported = `<aml version="0.2">
  <agents>
    <agent id="writer" instructions="write imported" />
  </agents>
  <graph id="phase">
    <nodes>
      <agent id="inner" ref="#writer" />
    </nodes>
    <edges>
      <edge from="entry" to="inner" />
      <edge from="inner" to="exit" />
    </edges>
  </graph>
</aml>`;

  vibe.ingestDocument({
    uri,
    fileName: 'main.aml',
    languageId: 'aml',
    text: source,
    importedDocuments: {
      simple: {
        alias: 'simple',
        filePath: '/workspace/simple.aml',
        text: imported
      }
    }
  });

  assert.equal(vibe.docs[uri].graph?.Nodes.some((node: any) => node.name === 'phase__inner'), true);

  vibe.ingestDocument({
    uri,
    fileName: 'main.aml',
    languageId: 'aml',
    text: source
  });

  assert.equal(vibe.docs[uri].graph?.Nodes.some((node: any) => node.name === 'phase__inner'), true);
  assert.equal(vibe.docs[uri].amlImportedDocuments?.simple && typeof vibe.docs[uri].amlImportedDocuments.simple, 'object');
});

test('AML imported graph edits serialize back to the imported AML file', () => {
  const source = `<?xml version="1.0" encoding="UTF-8"?>
<aml version="0.2">
  <imports>
    <import alias="simple" src="./simple.aml" />
  </imports>
  <graph id="root" kind="root">
    <nodes>
      <graph id="phase" ref="simple::phase" />
    </nodes>
    <edges>
      <edge from="entry" to="phase" />
      <edge from="phase" to="exit" />
    </edges>
  </graph>
</aml>`;
  const imported = `<aml version="0.2">
  <agents>
    <agent id="writer" instructions="write imported" />
  </agents>
  <graph id="phase">
    <nodes>
      <agent id="inner" ref="#writer" />
    </nodes>
    <edges>
      <edge from="entry" to="inner" />
      <edge from="inner" to="exit" />
    </edges>
  </graph>
</aml>`;
  const importedDocuments = {
    simple: {
      alias: 'simple',
      filePath: '/workspace/simple.aml',
      text: imported
    }
  };

  const parsed = parseAmlGraphDesign(source, { importedDocuments }).graph;
  const inner = parsed.Nodes.find((node) => node.name === 'phase__inner') as any;
  inner.label = 'Edited inner';
  parsed.Nodes.push({
    name: 'phase__review',
    type: 'CustomNode',
    label: 'review',
    parent: 'phase',
    forward_body: 'builtin:noop',
    __aml_from_ref: true,
    __aml_ref: 'simple::phase',
    __aml_ref_graphId: 'phase',
    __aml_ref_filePath: '/workspace/simple.aml',
    __aml_external_parent: 'phase',
    __aml_external_local_name: 'review'
  } as any);
  parsed.Edges.push({
    from: 'phase__inner',
    to: 'phase__review',
    __aml_from_ref: true,
    __aml_ref: 'simple::phase',
    __aml_ref_graphId: 'phase',
    __aml_ref_filePath: '/workspace/simple.aml',
    __aml_external_parent: 'phase'
  } as any);

  const parentSaved = serializeAmlGraphDesign(source, parsed);
  assert.doesNotMatch(parentSaved, /phase__review/);

  const writes = serializeAmlExternalGraphEdits(parsed, importedDocuments);
  assert.equal(writes.length, 1);
  assert.equal(writes[0].filePath, '/workspace/simple.aml');
  assert.match(writes[0].text, /<agent id="inner" label="Edited inner" ref="#writer" \/>/);
  assert.match(writes[0].text, /<custom_node id="review" forward="builtin:noop" \/>/);
  assert.match(writes[0].text, /<edge from="inner" to="review" \/>/);
});

test('AML nested imported refs write back to their own source AML file', () => {
  const source = `<aml version="0.2">
  <imports><import alias="composed" src="./composed.aml" /></imports>
  <graph id="root" kind="root">
    <nodes><graph id="phase" ref="composed::phase" /></nodes>
    <edges><edge from="entry" to="phase" /><edge from="phase" to="exit" /></edges>
  </graph>
</aml>`;
  const composed = `<aml version="0.2">
  <imports><import alias="simple" src="./simple.aml" /></imports>
  <graph id="phase">
    <nodes><graph id="inner_phase" ref="simple::inner" /></nodes>
    <edges><edge from="entry" to="inner_phase" /><edge from="inner_phase" to="exit" /></edges>
  </graph>
</aml>`;
  const simple = `<aml version="0.2">
  <graph id="inner">
    <nodes><custom_node id="worker" forward="builtin:noop" /></nodes>
    <edges><edge from="entry" to="worker" /><edge from="worker" to="exit" /></edges>
  </graph>
</aml>`;
  const importedDocuments = {
    composed: { alias: 'composed', filePath: '/workspace/composed.aml', text: composed },
    simple: { alias: 'simple', filePath: '/workspace/simple.aml', text: simple }
  };

  const parsed = parseAmlGraphDesign(source, { importedDocuments }).graph;
  const worker = parsed.Nodes.find((node) => node.name === 'phase__inner_phase__worker') as any;
  assert.equal(worker?.__aml_ref_filePath, '/workspace/simple.aml');
  assert.equal(worker?.__aml_external_parent, 'phase__inner_phase');
  worker.label = 'Edited worker';

  const writes = serializeAmlExternalGraphEdits(parsed, importedDocuments);
  const simpleWrite = writes.find((write) => write.filePath === '/workspace/simple.aml');
  assert.ok(simpleWrite);
  assert.match(simpleWrite!.text, /<custom_node id="worker" label="Edited worker" forward="builtin:noop" \/>/);
});

test('AML imported graph can be opened directly by requested graph id', () => {
  const source = `<aml version="0.2">
  <graph id="first">
    <nodes><agent id="first_agent" ref="#agent" /></nodes>
    <edges><edge from="entry" to="first_agent" /><edge from="first_agent" to="exit" /></edges>
  </graph>
  <graph id="second">
    <nodes><custom_node id="second_node" forward="builtin:noop" /></nodes>
    <edges><edge from="entry" to="second_node" /><edge from="second_node" to="exit" /></edges>
  </graph>
</aml>`;

  const parsed = parseAmlGraphDesign(source, { graphId: 'second' }).graph;
  assert.equal(parsed.Nodes.some((node) => node.name === 'second_node'), true);
  assert.equal(parsed.Nodes.some((node) => node.name === 'first_agent'), false);

  const saved = serializeAmlGraphDesign(source, {
    ...parsed,
    Nodes: [{ name: 'renamed_second_node', type: 'CustomNode', forward_body: 'builtin:noop' }],
    Edges: [
      { from: 'entry', to: 'renamed_second_node' },
      { from: 'renamed_second_node', to: 'exit' }
    ],
    [AML_ACTIVE_GRAPH_ID_KEY]: 'second'
  });
  assert.match(saved, /id="first_agent"/);
  assert.match(saved, /id="renamed_second_node"/);
  assert.doesNotMatch(saved, /id="second_node"/);
});
