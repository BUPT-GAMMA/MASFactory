const path = require('path');

async function main() {
    const { Parser, Language } = await import('web-tree-sitter');

    const mediaDir = path.join(__dirname, 'media');
    const engineWasmPath = path.join(mediaDir, 'tree-sitter.wasm');
    const pythonWasmPath = path.join(mediaDir, 'tree-sitter-python.wasm');

    await Parser.init({
        locateFile: () => engineWasmPath,
    });
    const Python = await Language.load(pythonWasmPath);

    const parser = new Parser();
    parser.setLanguage(Python);

const code = `
pre_processing_node = chatdev_lite_auto.create_node(
    AgentNode,
    name="pre_processing",
)
`;

    const tree = parser.parse(code);
    if (!tree) {
        throw new Error('Failed to parse: Tree-sitter not initialized or language not loaded');
    }
const rootNode = tree.rootNode;

console.log('Root node type:', rootNode.type);
console.log('Root children count:', rootNode.children.length);

for (const child of rootNode.children) {
    if (!child) continue;
    console.log('Child type:', child.type);
    console.log('Child named children count:', child.namedChildren.length);
    const firstNamed = child.namedChildren.find((n) => !!n);
    if (firstNamed) {
        console.log('First named child type:', firstNamed.type);
    }
}
}

main().catch((err) => {
    console.error(err);
    process.exitCode = 1;
});
