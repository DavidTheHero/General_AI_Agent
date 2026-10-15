import { FinanceMcpClient } from "./client.js";

const client = new FinanceMcpClient();
try {
    const [name = "list", args = "{}"] = process.argv.slice(2);
    if (name === "list") {
        await client.connect();
        console.log(JSON.stringify(client.tools, null, 2));
    } else {
        console.log(JSON.stringify(await client.call(name, JSON.parse(args)), null, 2));
    }
} catch (error) {
    console.error(error.message);
    process.exitCode = 1;
} finally {
    await client.close();
}
