const fs = require('fs');

function patchStream(stream, fd) {
  const originalWrite = stream.write.bind(stream);

  stream.write = function write(chunk, encoding, callback) {
    try {
      if (typeof encoding === 'function') {
        callback = encoding;
        encoding = undefined;
      }

      const buffer = Buffer.isBuffer(chunk)
        ? chunk
        : Buffer.from(String(chunk), encoding || 'utf8');

      fs.writeSync(fd, buffer);
      if (typeof callback === 'function') callback();
      return true;
    } catch (error) {
      return originalWrite(chunk, encoding, callback);
    }
  };
}

patchStream(process.stdout, 1);
patchStream(process.stderr, 2);

