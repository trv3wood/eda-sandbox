module fsm(input logic clk, reset_n, start, done,
           output logic busy);
  typedef enum logic {IDLE, ACTIVE} state_t;
  state_t state;
  always_ff @(posedge clk or negedge reset_n) begin
    if (!reset_n) state <= IDLE;
    else case (state)
      IDLE: if (start) state <= ACTIVE;
      ACTIVE: if (done) state <= IDLE;
    endcase
  end
  assign busy = state == ACTIVE;
endmodule

