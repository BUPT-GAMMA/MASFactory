import assert from 'node:assert/strict';
import * as fs from 'node:fs';
import { createRequire } from 'node:module';
import * as path from 'node:path';
import { parseAppInboundMessage, parseWebviewOutboundMessage } from '../shared/webviewProtocol';

const requireForTest = createRequire(__filename);
const ModuleLoader = requireForTest('node:module') as any;

describe('AML visualizer support', () => {
  const extensionRoot = path.resolve(__dirname, '..', '..');

  it('contributes AML as a VS Code language with a grammar', () => {
    const packageJson = JSON.parse(fs.readFileSync(path.join(extensionRoot, 'package.json'), 'utf8'));
    const languages = Array.isArray(packageJson.contributes?.languages)
      ? packageJson.contributes.languages
      : [];
    const grammars = Array.isArray(packageJson.contributes?.grammars)
      ? packageJson.contributes.grammars
      : [];

    const amlLanguage = languages.find((item: any) => item?.id === 'aml');
    const amlGrammar = grammars.find((item: any) => item?.language === 'aml');

    assert.equal(amlLanguage?.configuration, './language-configuration-aml.json');
    assert.deepEqual(amlLanguage?.extensions, ['.aml']);
    assert.equal(amlGrammar?.scopeName, 'text.xml.aml');
    assert.equal(amlGrammar?.path, './syntaxes/aml.tmLanguage.json');

    assert.doesNotThrow(() => {
      JSON.parse(fs.readFileSync(path.join(extensionRoot, 'language-configuration-aml.json'), 'utf8'));
      JSON.parse(fs.readFileSync(path.join(extensionRoot, 'syntaxes/aml.tmLanguage.json'), 'utf8'));
    });
  });

  it('preserves AML language metadata in Vibe document messages', () => {
    const msg = parseAppInboundMessage({
      type: 'vibeDocument',
      documentUri: 'file:///workspace/main.aml',
      fileName: 'main.aml',
      text: '<aml kind="graph"></aml>',
      languageId: 'aml',
      amlGraphId: 'phase',
      implementationGraphs: {
        'python:project.workflow.Phase': { nodes: ['entry', 'exit'], edges: [] }
      },
      implementationTargets: {
        'python:project.workflow.Phase': { filePath: '/workspace/phase.py', line: 12 }
      },
      importedDocuments: {
        simple: { alias: 'simple', filePath: '/workspace/simple.aml', text: '<aml version="0.2" />' }
      }
    });

    assert.equal(msg?.type, 'vibeDocument');
    assert.equal(msg?.languageId, 'aml');
    assert.equal((msg as any)?.amlGraphId, 'phase');
    assert.deepEqual((msg as any)?.implementationGraphs?.['python:project.workflow.Phase']?.nodes, ['entry', 'exit']);
    assert.equal((msg as any)?.implementationTargets?.['python:project.workflow.Phase']?.filePath, '/workspace/phase.py');
    assert.equal((msg as any)?.importedDocuments?.simple?.filePath, '/workspace/simple.aml');
  });

  it('parses openFileLocation tab and AML graph navigation metadata', () => {
    const msg = parseWebviewOutboundMessage({
      type: 'openFileLocation',
      filePath: '/workspace/simple.aml',
      line: 20,
      targetTab: 'drag',
      amlGraphId: 'phase'
    });

    assert.equal(msg?.type, 'openFileLocation');
    assert.equal((msg as any)?.targetTab, 'drag');
    assert.equal((msg as any)?.amlGraphId, 'phase');
  });

  it('parses Vibe save extra writes for imported AML refs', () => {
    const msg = parseWebviewOutboundMessage({
      type: 'vibeSave',
      documentUri: 'file:///workspace/main.aml',
      text: '<aml version="0.2" />',
      extraWrites: [
        {
          filePath: '/workspace/simple.aml',
          text: '<aml version="0.2"><graph id="phase" /></aml>'
        }
      ]
    });

    assert.equal(msg?.type, 'vibeSave');
    assert.equal((msg as any)?.extraWrites?.[0]?.filePath, '/workspace/simple.aml');
    assert.match((msg as any)?.extraWrites?.[0]?.text, /graph id="phase"/);
  });

  it('waits for parser readiness before resolving AML python implementation previews', async () => {
    const originalLoad = ModuleLoader._load;
    const vscodeMock = {
      workspace: {
        workspaceFolders: [{ uri: { fsPath: '/workspace' } }],
        getWorkspaceFolder: () => ({ uri: { fsPath: '/workspace' } })
      },
      Uri: {
        parse: (value: string) => ({ fsPath: value.replace(/^file:\/\//, '') })
      },
      window: {
        activeTextEditor: undefined
      }
    };

    ModuleLoader._load = function loadWithVscodeMock(this: unknown, request: string, parent: unknown, isMain: boolean) {
      if (request === 'vscode') {
        return vscodeMock;
      }
      return originalLoad.apply(this, [request, parent, isMain]);
    };

    let PreviewGraphService: any;
    try {
      ({ PreviewGraphService } = await import('../webview/previewGraphService.js'));
    } finally {
      ModuleLoader._load = originalLoad;
    }

    let ready = false;
    let releaseReady: () => void = () => {};
    const parserReady = new Promise<void>((resolve) => {
      releaseReady = () => {
        ready = true;
        resolve();
      };
    });
    let parserCalls = 0;
    const parser = {
      setFileReader() {},
      async getComponentStructureByPythonPath(binding: string) {
        parserCalls += 1;
        assert.equal(ready, true);
        assert.equal(binding, 'python:project.workflow.Phase');
        return {
          nodes: ['entry', 'inside', 'exit'],
          nodeTypes: { entry: 'entry', inside: 'CustomNode', exit: 'exit' },
          nodeLineNumbers: { inside: 7 },
          nodePullKeys: {},
          nodePushKeys: {},
          nodeAttributes: {},
          edges: [
            { from: 'entry', to: 'inside', keys: [] },
            { from: 'inside', to: 'exit', keys: [] }
          ],
          subgraphs: {},
          hasComplexStructure: false,
          sourceFilePath: '/workspace/phase.py'
        };
      },
      async getComponentStructure() {
        return null;
      }
    };

    const service = new PreviewGraphService({
      parser,
      controlFlowState: {},
      safePostMessage() {},
      ensureParserReady: () => parserReady
    });
    const document = {
      languageId: 'aml',
      uri: {
        fsPath: '/workspace/main.aml',
        toString: () => 'file:///workspace/main.aml'
      },
      fileName: '/workspace/main.aml',
      getText: () =>
        '<aml version="0.2"><graph id="root" kind="root"><nodes><graph id="phase" implementation="python:project.workflow.Phase" /></nodes></graph></aml>'
    };

    const pending = service.resolveAmlPreviewData(document);
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(parserCalls, 0);

    releaseReady();
    const previewData = await pending;

    assert.equal(parserCalls, 1);
    assert.equal(previewData.implementationGraphs['python:project.workflow.Phase'].nodes.includes('inside'), true);
  });
});
