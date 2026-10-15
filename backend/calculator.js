// Parse arithmetic only; never execute model-generated JavaScript.
export function calculate(expression) {
    const tokens = expression.match(/\d+(?:\.\d*)?(?:[eE][+-]?\d+)?|\.\d+|\*\*|\/\/|[()+*/%\-]|\S/g) || [];
    let index = 0;
    function primary() {
        const token = tokens[index++];
        if (token === "(") {
            const result = sum();
            if (tokens[index++] !== ")") throw new Error("Expected a closing parenthesis.");
            return result;
        }
        if (!token || !/^(?:\d|\.\d)/.test(token)) throw new Error("Invalid arithmetic expression.");
        return Number(token);
    }
    function power() {
        let result = primary();
        if (tokens[index] === "**") {
            index++;
            result **= unary();
        }
        return result;
    }
    function unary() {
        if (tokens[index] === "+" || tokens[index] === "-") {
            return tokens[index++] === "-" ? -unary() : unary();
        }
        return power();
    }
    function product() {
        let result = unary();
        while (["*", "/", "//", "%"].includes(tokens[index])) {
            const op = tokens[index++];
            const right = unary();
            if (right === 0 && op !== "*") throw new Error("Division by zero.");
            if (op === "*") result *= right;
            if (op === "/") result /= right;
            if (op === "//") result = Math.floor(result / right);
            if (op === "%") result = result - Math.floor(result / right) * right;
        }
        return result;
    }
    function sum() {
        let result = product();
        while (tokens[index] === "+" || tokens[index] === "-") {
            const op = tokens[index++];
            const right = product();
            result = op === "+" ? result + right : result - right;
        }
        return result;
    }
    const result = sum();
    if (index !== tokens.length || !Number.isFinite(result)) throw new Error("Invalid arithmetic expression.");
    return result;
}
