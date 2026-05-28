// SPDX-License-Identifier: MIT
// Copyright (C) 2026 Leonardo Capossio - bard0 design
// Equivalent "translation" of counter_gold.v, written in a different style
// (explicit next-state two-process form). Behaviorally identical: reset still
// dominates enable. Should PASS every parity layer.
`timescale 1ns / 1ps

module counter #(
    parameter WIDTH = 8
) (
    input  wire             clk,
    input  wire             rst,
    input  wire             en,
    output reg  [WIDTH-1:0] count
);
    reg [WIDTH-1:0] next;

    always @* begin
        next = count;
        if (en)
            next = count + 1'b1;
        if (rst)
            next = {WIDTH{1'b0}};
    end

    always @(posedge clk)
        count <= next;

    initial count = {WIDTH{1'b0}};
endmodule
